"""When to remind the player to run Anki's Optimize All Presets, and what the reminder says.

    collection (config, deck config, revlog) ──inputs──▶ Inputs ──verdict──▶ Silent | Remind
    state (synced setting) ──next_state──▶ state

The rule is AnkiQuest-Server's crates/rules (optimize_verdict, optimize_next), tested against
tests/fixtures/optimize_reminder.json. This is a copy tested against the same cases, as Android's
AnkiquestOptimizeReminder.kt is; it goes once the add-on uses the crate's bindings. The inputs
come from the collection. The state is the synced setting `optimize_reminder`, one for all the
player's devices (settings_sync). Its times are epoch milliseconds, never collection day numbers:
collections on different devices can number their days differently. Plain Python, so the tests
load it without Anki.
"""

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Union

DAYS = 30
REVIEWS = 1000
SNOOZE_DAYS = 7
DAY_MS = 86_400_000

# The add-on config key that holds the state; settings_sync syncs it as the key of the same name.
CONFIG_KEY = "optimize_reminder"
DEFAULT = {"kind": "on"}
# The collection config key Optimize All Presets sets to the day it ran; 0 or missing is never.
LAST_OPTIMIZE_KEY = "lastFsrsOptimize"
DAY_SECONDS = 86_400
# Times fit the 64-bit integers the rule uses.
MAX_MS = 2**63 - 1
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
    """Hidden while now is before until_ms."""
    until_ms: int


@dataclass(frozen=True)
class Dismissed:
    """Hidden until Optimize All Presets runs again: until a run a day or more after
    optimized_ms, the last one when it was dismissed (None: it had never run)."""
    optimized_ms: Optional[int]


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
    """What the rule reads from the collection, and the time now."""
    now_ms: int
    last_optimized_ms: Optional[int]
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


def optimized_since(dismissed, last):
    """Whether Optimize All Presets ran again after `dismissed`. A run counts only from a day
    later: devices in other time zones put the end of the same collection day hours apart."""
    if last is None:
        return False
    if dismissed is None:
        return True
    return last >= dismissed + DAY_MS


def verdict(inputs, state):
    now = inputs.now_ms
    last = inputs.last_optimized_ms
    optimized = [preset for preset in inputs.presets if preset is not Scheduler.SM2]

    # The first rule that holds names the verdict.
    if isinstance(state, Off):
        return Silent(Quiet.OFF)
    if not optimized:
        return Silent(Quiet.NO_FSRS)
    if isinstance(state, Snoozed) and now < state.until_ms:
        return Silent(Quiet.SNOOZED)
    if isinstance(state, Dismissed) and not optimized_since(state.optimized_ms, last):
        return Silent(Quiet.DISMISSED)
    if last is not None and now - last < DAYS * DAY_MS:
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


def next_state(state, event, now_ms, last_optimized_ms):
    if event is Event.TURN_OFF:
        return Off()
    if isinstance(state, Off) and event is Event.TURN_ON:
        return On()
    if isinstance(state, Off) or event is Event.TURN_ON:
        return state
    if event is Event.SNOOZE:
        return Snoozed(now_ms + SNOOZE_DAYS * DAY_MS)
    return Dismissed(last_optimized_ms)


def optimized_at(today, day_cutoff, last_optimized_day):
    """When Optimize All Presets last ran, in epoch ms: the end of the collection day it ran,
    since Anki records only the day. None when it never ran."""
    if last_optimized_day is None:
        return None
    return (day_cutoff - (today - last_optimized_day) * DAY_SECONDS) * SECOND_MS


def reviews_since(db, last_optimized_ms):
    """Answers since last_optimized_ms, or every answer when it never ran."""
    start = 0 if last_optimized_ms is None else last_optimized_ms
    return db.scalar(ANSWERS_SQL, start) or 0


def now_ms():
    return int(time.time() * SECOND_MS)


def last_optimized(col):
    value = col.get_config(LAST_OPTIMIZE_KEY, 0)
    return value if isinstance(value, int) and value > 0 else None


def inputs(col, now):
    """Reads the rule's inputs from an open collection, at `now` in epoch ms."""
    last = optimized_at(col.sched.today, col.sched.day_cutoff, last_optimized(col))
    fsrs = Fsrs.ON if col.get_config("fsrs", False) else Fsrs.OFF
    return Inputs(
        now_ms=now,
        last_optimized_ms=last,
        reviews_since=reviews_since(col.db, last),
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
        return Snoozed(stored["until_ms"])
    if kind == "dismissed":
        return Dismissed(stored["optimized_ms"])
    return On()


def _ms(value, first):
    return type(value) is int and first <= value <= MAX_MS


def valid(stored):
    """Whether `stored` is a state exactly as encode writes it, with times in epoch ms: the form
    the server accepts for the synced setting."""
    if not isinstance(stored, dict):
        return False
    kind = stored.get("kind")
    fields = set(stored) - {"kind"}
    if kind in ("on", "off"):
        return not fields
    if kind == "snoozed":
        return fields == {"until_ms"} and _ms(stored["until_ms"], 0)
    if kind == "dismissed":
        ms = stored.get("optimized_ms", 0)
        return fields == {"optimized_ms"} and (ms is None or _ms(ms, 1))
    return False


def encode(state):
    if isinstance(state, Off):
        return {"kind": "off"}
    if isinstance(state, Snoozed):
        return {"kind": "snoozed", "until_ms": state.until_ms}
    if isinstance(state, Dismissed):
        return {"kind": "dismissed", "optimized_ms": state.optimized_ms}
    return {"kind": "on"}


def message(remind, translate):
    """The reminder's text: the since line, the scheduler line, then where the button is."""
    return " ".join(translate(text) for text in (SINCE_TEXT[remind.since], WORDING_TEXT[remind.wording], WHERE))
