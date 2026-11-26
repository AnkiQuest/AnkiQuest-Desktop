"""When to remind the player to run Anki's Optimize All Presets, and what the reminder says.

    collection (config, deck config, revlog) ──inputs──▶ Inputs ──verdict──▶ Silent | Remind
    state (synced setting) ──next_state──▶ state

The rule is AnkiQuest-Server's crates/rules (optimize_verdict, optimize_next), tested against
tests/fixtures/optimize_reminder.json. This is a copy tested against the same cases, as Android's
AnkiquestOptimizeReminder.kt is; it goes once the add-on uses the crate's bindings. The inputs
come from the collection. The state is the synced setting `optimize_reminder`, one for all the
player's devices (settings_sync). Plain Python, so the tests load it without Anki.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Union

DAYS = 30
REVIEWS = 1000
SNOOZE_DAYS = 7

# The add-on config key that holds the state; settings_sync syncs it as the key of the same name.
CONFIG_KEY = "optimize_reminder"
DEFAULT = {"kind": "on"}
# The collection config key Optimize All Presets sets to the day it ran; 0 or missing is never.
LAST_OPTIMIZE_KEY = "lastFsrsOptimize"
DAY_SECONDS = 86_400
# Day numbers fit the 32-bit integers the rule uses.
MAX_DAY = 2**31 - 1
SECOND_MS = 1_000

# Answers only: manual (type 4) and rescheduled (type 5) entries are not reviews.
ANSWERS_SQL = "select count() from revlog where id >= ? and ease > 0 and type < 4"


class Scheduler(Enum):
    SM2 = "sm2"
    FSRS = "fsrs"
    RWKV_CURVE = "rwkv_curve"
    RWKV_INSTANT = "rwkv_instant"


class Fsrs(Enum):
    """Whether the collection uses FSRS; without it every preset is SM-2."""
    ON = auto()
    OFF = auto()


@dataclass(frozen=True)
class On:
    pass


@dataclass(frozen=True)
class Off:
    """Turned off by the settings switch."""


@dataclass(frozen=True)
class Snoozed:
    """Hidden while today is before until_day."""
    until_day: int


@dataclass(frozen=True)
class Dismissed:
    """Hidden until Optimize All Presets runs again: while it last ran on optimized_day."""
    optimized_day: Optional[int]


State = Union[On, Off, Snoozed, Dismissed]


class Event(Enum):
    SNOOZE = "snooze"
    DISMISS = "dismiss"
    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"


class Quiet(Enum):
    """Why there is no reminder, in the order the rule checks."""
    OFF = "off"
    NO_FSRS = "no_fsrs"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    TOO_SOON = "too_soon"
    TOO_FEW_REVIEWS = "too_few_reviews"


class Since(Enum):
    STALE = "stale"
    NEVER = "never"


class Wording(Enum):
    """What optimizing does for the presets: FSRS parameters, the RWKV presets' FSRS fallback, or both."""
    FSRS = "fsrs"
    RWKV = "rwkv"
    MIXED = "mixed"


@dataclass(frozen=True)
class Silent:
    quiet: Quiet


@dataclass(frozen=True)
class Remind:
    since: Since
    wording: Wording


@dataclass(frozen=True)
class Inputs:
    """What the rule reads from the collection."""
    today: int
    last_optimized_day: Optional[int]
    reviews_since: int
    presets: list
    deck: int


# The English text, in the fixture's order; language.tr translates each.
TITLE = "Time to optimize your presets"
SINCE_TEXT = {
    Since.STALE: "You last ran Optimize All Presets at least 30 days and 1,000 reviews ago.",
    Since.NEVER: "You have at least 1,000 reviews and haven't run Optimize All Presets yet.",
}
WORDING_TEXT = {
    Wording.FSRS: "It fits each preset's FSRS parameters to your review history.",
    Wording.RWKV: "Your presets use RWKV-Curve or RWKV-Instant: it fits only their FSRS fallback. RWKV itself isn't trained by it.",
    Wording.MIXED: (
        "It fits the parameters of your FSRS presets to your review history. For RWKV-Curve and "
        "RWKV-Instant presets it fits only the FSRS fallback; RWKV itself isn't trained by it."
    ),
}
WHERE = "Optimize All Presets is in the FSRS section of deck options."
OPEN = "Open deck options"
SNOOZE = "Remind me in a week"
DISMISS = "Dismiss"
SETTING = "Remind me to optimize presets"
SETTING_SUMMARY = "When Optimize All Presets last ran at least 30 days and 1,000 reviews ago"


def scheduler(fsrs, config):
    """A preset's scheduler from its legacy deck config dict."""
    if fsrs is Fsrs.OFF:
        return Scheduler.SM2
    if config.get("rwkvReviewInstantOrderEnabled"):
        return Scheduler.RWKV_INSTANT
    if config.get("rwkvReviewEnabled"):
        return Scheduler.RWKV_CURVE
    return Scheduler.FSRS


def verdict(inputs, state):
    last = inputs.last_optimized_day
    optimized = [preset for preset in inputs.presets if preset is not Scheduler.SM2]

    # The first rule that holds names the verdict.
    if isinstance(state, Off):
        return Silent(Quiet.OFF)
    if not optimized:
        return Silent(Quiet.NO_FSRS)
    if isinstance(state, Snoozed) and inputs.today < state.until_day:
        return Silent(Quiet.SNOOZED)
    if isinstance(state, Dismissed) and state.optimized_day == last:
        return Silent(Quiet.DISMISSED)
    if last is not None and inputs.today - last < DAYS:
        return Silent(Quiet.TOO_SOON)
    if inputs.reviews_since < REVIEWS:
        return Silent(Quiet.TOO_FEW_REVIEWS)

    fsrs = sum(1 for preset in optimized if preset is Scheduler.FSRS)
    if fsrs == 0:
        wording = Wording.RWKV
    elif fsrs == len(optimized):
        wording = Wording.FSRS
    else:
        wording = Wording.MIXED
    return Remind(Since.NEVER if last is None else Since.STALE, wording)


def next_state(state, event, today, last_optimized_day):
    if event is Event.TURN_OFF:
        return Off()
    if isinstance(state, Off) and event is Event.TURN_ON:
        return On()
    if isinstance(state, Off) or event is Event.TURN_ON:
        return state
    if event is Event.SNOOZE:
        return Snoozed(today + SNOOZE_DAYS)
    return Dismissed(last_optimized_day)


def reviews_since(db, today, day_cutoff, last_optimized_day):
    """Answers on the days after last_optimized_day, or every answer when it never ran."""
    start = 0
    if last_optimized_day is not None:
        start = (day_cutoff - (today - last_optimized_day) * DAY_SECONDS) * SECOND_MS
    return db.scalar(ANSWERS_SQL, start) or 0


def last_optimized(col):
    value = col.get_config(LAST_OPTIMIZE_KEY, 0)
    return value if isinstance(value, int) and value > 0 else None


def inputs(col):
    """Reads the rule's inputs from an open collection."""
    today = col.sched.today
    last = last_optimized(col)
    fsrs = Fsrs.ON if col.get_config("fsrs", False) else Fsrs.OFF
    return Inputs(
        today=today,
        last_optimized_day=last,
        reviews_since=reviews_since(col.db, today, col.sched.day_cutoff, last),
        presets=[scheduler(fsrs, config) for config in col.decks.all_config()],
        deck=col.decks.get_current_id(),
    )


def decode(stored):
    """The state in its stored form; one that is not exactly a state reads as on."""
    if not valid(stored):
        return On()
    kind = stored["kind"]
    if kind == "off":
        return Off()
    if kind == "snoozed":
        return Snoozed(stored["until_day"])
    if kind == "dismissed":
        return Dismissed(stored["optimized_day"])
    return On()


def _day(value, first):
    return type(value) is int and first <= value <= MAX_DAY


def valid(stored):
    """Whether `stored` is a state exactly as encode writes it, with days a collection has: the
    form the server accepts for the synced setting."""
    if not isinstance(stored, dict):
        return False
    kind = stored.get("kind")
    fields = set(stored) - {"kind"}
    if kind in ("on", "off"):
        return not fields
    if kind == "snoozed":
        return fields == {"until_day"} and _day(stored["until_day"], 0)
    if kind == "dismissed":
        day = stored.get("optimized_day", 0)
        return fields == {"optimized_day"} and (day is None or _day(day, 1))
    return False


def encode(state):
    if isinstance(state, Off):
        return {"kind": "off"}
    if isinstance(state, Snoozed):
        return {"kind": "snoozed", "until_day": state.until_day}
    if isinstance(state, Dismissed):
        return {"kind": "dismissed", "optimized_day": state.optimized_day}
    return {"kind": "on"}


def message(remind, translate):
    """The reminder's text: the since line, the scheduler line, then where the button is."""
    return " ".join(translate(text) for text in (SINCE_TEXT[remind.since], WORDING_TEXT[remind.wording], WHERE))
