"""The companion's mood for today, and its artwork, chosen like the phone app's Aki.

Two rules live here. `streak_mood` picks the pose, and `flame` the flame beside the streak
number, from today's streak, as the phone's AnkiquestMood does, pinned by
tests/fixtures/streak_moods.json. `mood` picks the encouraging line from that streak mood
first, then from the collection's due cards, as the phone's AnkiquestAki.message does.
"""

from dataclasses import dataclass
from enum import Enum, auto
import json
from pathlib import Path

WELCOME, REVIEW, CELEBRATE, STREAK, FREEZE, WINNER = "welcome", "review", "celebrate", "streak", "freeze", "winner"

MOODS = (WELCOME, REVIEW, CELEBRATE, STREAK, FREEZE, WINNER)

# Each mood's line. Cards due (REVIEW) get none: the next-step card below already says what to do.
MESSAGES = {
    WELCOME: "Aki is here to help. One card, one small step.",
    CELEBRATE: "Your cards are done for now. Nice work!",
    STREAK: "You showed up today. That is progress worth keeping.",
    FREEZE: "Your streak is protected by a freeze. A fresh start is waiting.",
    WINNER: "Every quest is done today. Nice work!",
}

COMPANION_WELCOME = "One card, one small step."

# A streak waiting for today's study (Android's aki_streak_waiting). It has no pose of its own:
# the sad streak pose shows. The one-day form names its day, so translations can agree with it.
WAITING = "waiting"
WAITING_LINES = (
    "You haven’t studied today. Your 1-day streak is still waiting.",
    "You haven’t studied today. Your %d-day streak is still waiting.",
)

# Today's day verdict, as the fixture names it.
STUDIED, PROTECTED, SHORT, PENDING, UNKNOWN = "studied", "protected", "short", "pending", "unknown"

# The displayed day's `_day_status` (day_verdict._for_display) to its verdict; pending splits by reviews.
_DAY_STATES = {"met": STUDIED, "unverified": STUDIED, "syncing": STUDIED, "protected": PROTECTED, "pending": PENDING}

# Aki's streak moods, as the phone names them.
STREAK_MOODS = (
    "unknown", "asleep", "sad", "freeze", "frozen_1", "frozen_2", "frozen_3", "thawing", "hopeful", "almost", "fire",
    "neglected", "abandoned", "dead",
)
(MOOD_UNKNOWN, ASLEEP, SAD, MOOD_FREEZE, FROZEN_1, FROZEN_2, FROZEN_3, THAWING, HOPEFUL, ALMOST, FIRE,
 NEGLECTED, ABANDONED, DEAD) = STREAK_MOODS

# Days without reviews in a row ending yesterday, and the away mood each count starts, as
# `away_levels` in streak_moods.json says; later levels first.
AWAY_LEVELS = ((30, DEAD), (7, ABANDONED), (2, NEGLECTED))

# How long before the study day ends a freeze about to keep the streak shows as one
# (`freeze_window_ms`).
FREEZE_WINDOW_MS = 7_200_000

MINUTE_MS = 60_000
_PERCENT = 100

# The moods a freeze kept the streak in.
_FROZEN = (FROZEN_1, FROZEN_2, FROZEN_3)

# The companion tab's line for each mood, saying why; `%d` is the streak.
MOOD_LINES = {
    MOOD_UNKNOWN: "Waiting for today’s study to sync.",
    ASLEEP: "Asleep: study a card to start a streak.",
    MOOD_FREEZE: "Wrapped up: a freeze is keeping your %d-day streak.",
    NEGLECTED: "Lonely: a few days without study. One card cheers me up.",
    ABANDONED: "Abandoned: a week without study. One card brings me back.",
    DEAD: "Out cold: a month without study. One card brings me back.",
    SAD: "Sad: your %d-day streak is waiting for today’s study.",
    FROZEN_1: "Frozen: a freeze kept your streak. Study today to thaw.",
    FROZEN_2: "Frozen for 2 days: study today to thaw.",
    FROZEN_3: "Frozen for 3 days or more: study today to thaw.",
    THAWING: "Thawing: keep studying and the freeze melts.",
    HOPEFUL: "Hopeful: a little more study and today counts.",
    ALMOST: "Almost: a few more minutes and today counts.",
    FIRE: "On fire: today counts for your %d-day streak.",
}

# The line for asleep at night with a streak (`night` in streak_moods.json).
NIGHT_LINE = "Asleep: your %d-day streak wakes up with you."

# A counted day's pose by heat: the first streak length each pose starts at, hottest first.
HEAT = ((100, "aki_streak_legend"), (30, "aki_streak_blazing"), (7, "aki_streak_hot"), (1, "aki_streak"))


class Flame(Enum):
    """The flame beside the streak number: lit only once today counts. Values as the fixture names them."""
    # No streak, or nothing known about today.
    NONE = "none"
    # Today counts: the usual flame.
    LIT = "lit"
    # A streak that today has not counted for yet: grey.
    UNLIT = "unlit"
    # A freeze kept the days before today, and today has not counted yet: icy blue.
    ICY = "icy"


# The flame for each streak mood, so the flame says what Aki would even with no companion shown.
_FLAMES = {
    MOOD_UNKNOWN: Flame.NONE,
    ASLEEP: Flame.NONE,
    NEGLECTED: Flame.NONE,
    ABANDONED: Flame.NONE,
    DEAD: Flame.NONE,
    SAD: Flame.UNLIT,
    MOOD_FREEZE: Flame.ICY,
    HOPEFUL: Flame.UNLIT,
    ALMOST: Flame.UNLIT,
    FROZEN_1: Flame.ICY,
    FROZEN_2: Flame.ICY,
    FROZEN_3: Flame.ICY,
    THAWING: Flame.ICY,
    FIRE: Flame.LIT,
}


class Yesterday(Enum):
    """How the study day before today ended, as `night` in streak_moods.json names it."""
    COUNTED = "counted"
    PROTECTED = "protected"
    MISSED = "missed"
    UNKNOWN = "unknown"


# The night window's rule: the usual first study time from the last RECENT_DAYS studied days,
# DEFAULT_USUAL with fewer than MIN_DAYS of them.
DAY_MINUTES = 24 * 60
HOUR_MINUTES = 60
DEFAULT_USUAL = "08:00"
RECENT_DAYS = 14
MIN_DAYS = 3

# Night asleep with a streak: the streak is alive but today has not counted yet.
NIGHT_FLAME = Flame.UNLIT


def after_rollover(time, rollover_hour):
    """Minutes after the study day's rollover for a local `HH:MM` time."""
    hours, minutes = (int(part) for part in time.split(":"))
    return (hours * HOUR_MINUTES + minutes - rollover_hour * HOUR_MINUTES) % DAY_MINUTES


def usual_first_study(first_reviews, rollover_hour):
    """The usual first study time, in minutes after rollover: the median (lower middle for an even
    count) of the last RECENT_DAYS first-review times, DEFAULT_USUAL with fewer than MIN_DAYS."""
    recent = sorted(after_rollover(time, rollover_hour) for time in list(first_reviews)[-RECENT_DAYS:])
    if len(recent) < MIN_DAYS:
        return after_rollover(DEFAULT_USUAL, rollover_hour)
    return recent[(len(recent) - 1) // 2]


@dataclass(frozen=True)
class Night:
    """What the night rule needs: the local time `now` (HH:MM), the day's `rollover_hour`, the
    first-review times of recent studied days (oldest first) and how yesterday ended."""
    now: str
    rollover_hour: int
    first_reviews: tuple
    yesterday: Yesterday

    def window(self):
        """Whether now is from the rollover up to, not including, the usual first study time."""
        usual = usual_first_study(self.first_reviews, self.rollover_hour)
        return after_rollover(self.now, self.rollover_hour) < usual


class Goal(Enum):
    """Whether today's daily goal is reached."""
    OPEN = auto()
    REACHED = auto()


class Stage(Enum):
    """How far today's review time has come toward the streak minimum. Each stage starts at
    `percent` of the minimum, as `stages` in streak_moods.json says; values as it names them."""
    STARTED = ("started", 0)
    QUARTER = ("quarter", 25)
    HALF = ("half", 50)
    THREE_QUARTERS = ("three_quarters", 75)

    def __new__(cls, name, percent):
        member = object.__new__(cls)
        member._value_ = name
        member.percent = percent
        return member

    @classmethod
    def of(cls, time_ms, streak_minutes):
        """The stage of `time_ms` toward `streak_minutes`, compared in whole numbers so no rounding
        moves a boundary. Without a minimum the first review counts the day, so it is STARTED."""
        if streak_minutes <= 0:
            return cls.STARTED
        time = max(0, time_ms) * _PERCENT
        goal_ms = streak_minutes * MINUTE_MS
        return [stage for stage in cls if time >= stage.percent * goal_ms][-1]


# The companions in the picker's order, and the names it shows; "none" is named by the picker.
AKI, ANKILOPE_ID, COW, ANKI_TAN, NONE = "aki", "ankilope", "cow", "anki_tan", "none"
NAMES = {AKI: "Aki", ANKILOPE_ID: "Ankilope", COW: "Bluma", ANKI_TAN: "Anki-tan"}

# The Aki poses each picker card previews, in the phone's order: face, fire, sad.
PREVIEW_POSES = ("aki_face", "aki_streak", "aki_sad")

# The poses AnkiQuest-Art's poses.json names, unpacked beside the code from the pinned release
# by the `-- art` step (tools/package-addon, `art`): the core poses every companion has, the pose
# each extension falls back to where a companion has no art for it, and the core pose a companion
# shows for a core pose it has no master for yet.


def read_poses(art):
    """The core poses, the extension fallbacks and the core fallbacks, as Art's `poses.json`
    (`core`, `extensions`, `core_fallbacks`) names them. Only pose names and name-to-name
    maps parse: anything else Art might write raises."""
    poses = json.loads(art)
    core = poses.get("core")
    if not isinstance(core, list) or not all(isinstance(pose, str) for pose in core):
        raise ValueError("Art's poses.json names no core poses")
    for field in ("extensions", "core_fallbacks"):
        names = poses.get(field)
        if not isinstance(names, dict) or not all(
            isinstance(pose, str) and isinstance(shown, str) for pose, shown in names.items()
        ):
            raise ValueError("Art's poses.json names no %s" % field)
    return (tuple(core), poses["extensions"], poses["core_fallbacks"])


# How a checkout unpacks the pictures and poses.json from the pinned AnkiQuest-Art release.
FETCH = "cargo run --locked --manifest-path tools/package-addon/Cargo.toml -- art"

try:
    _POSES_TEXT = Path(__file__).with_name("poses.json").read_text("utf-8")
except FileNotFoundError as error:
    raise RuntimeError("Fetch the companion pictures first: " + FETCH) from error
CORE_POSES, POSE_FALLBACKS, CORE_FALLBACKS = read_poses(_POSES_TEXT)

# The pose each moment, share-card and notification picture shows where a companion has no
# picture of its own, as poses.json `pictures` says. Only Aki has these scenes in the add-on.
PICTURE_FALLBACKS = {
    "achievement": "happy",
    "at_risk": "sad",
    "backlog": "sad",
    "challenge": "hopeful",
    "challenge_lost": "sad",
    "challenge_won": "winner",
    "comeback": "welcome",
    "deck_conquered": "happy",
    "freeze": "frozen",
    "freeze_used": "frozen",
    "goal": "happy",
    "level_up": "happy",
    "minimum": "review",
    "nudge": "hopeful",
    "place_1": "winner",
    "place_2": "happy",
    "place_3": "happy",
}

# Aki's pictures are `aki_<pose or picture>`.
_AKI_PREFIX = "aki_"

# The pose an Aki picture shows that neither the pose list nor `PICTURE_FALLBACKS` names, such
# as one a newer server sends: a full-body pose, never the face.
_UNKNOWN_PICTURE_POSE = "happy"

# The pose each of Aki's pictures shows, so that other companions show theirs.
_AKI_PICTURES = {
    "aki_face": "face",
    "aki_asleep": "asleep",
    "aki_celebrate": "happy",
    "aki_streak": "streak",
    "aki_streak_hot": "streak_hot",
    "aki_streak_blazing": "streak_blazing",
    "aki_streak_legend": "streak_legend",
    "aki_streak_milestone": "streak_milestone",
    "aki_at_risk": "sad",
    "aki_sad": "sad",
    "aki_hopeful": "hopeful",
    "aki_freeze_used": "frozen",
    "aki_frozen": "frozen",
    "aki_freeze": "frozen_2",
    "aki_neglected": "neglected",
    "aki_welcome": "welcome",
    "aki_review": "review",
    "aki_winner": "winner",
}

# The pose each streak mood shows; fire burns by heat (`HEAT`). thawing and almost are moods with
# no pose of their own (AnkiQuest-Server#45).
_MOOD_POSE_NAMES = {
    MOOD_UNKNOWN: "face",
    ASLEEP: "asleep",
    SAD: "sad",
    MOOD_FREEZE: "freeze",
    NEGLECTED: "neglected",
    ABANDONED: "abandoned",
    DEAD: "dead",
    FROZEN_1: "frozen",
    FROZEN_2: "frozen_2",
    FROZEN_3: "frozen_3",
    THAWING: "frozen",
    HOPEFUL: "hopeful",
    ALMOST: "hopeful",
}

# Aki's art for each pose she has, as the phone's AnkiquestCompanion maps them. She has no frozen 2
# or 3 art: those show her frozen pose.
AKI_POSES = {
    "face": "aki_face",
    "asleep": "aki_asleep",
    "happy": "aki_celebrate",
    "streak": "aki_streak",
    "streak_hot": "aki_streak_hot",
    "streak_blazing": "aki_streak_blazing",
    "streak_legend": "aki_streak_legend",
    "streak_milestone": "aki_streak_milestone",
    "sad": "aki_sad",
    "hopeful": "aki_hopeful",
    "frozen": "aki_frozen",
    "neglected": "aki_neglected",
}

# Ankilope's art for each pose she has, as the phone's AnkiquestCompanion maps them.
ANKILOPE = {
    "face": "ankilope_face",
    "asleep": "ankilope_asleep",
    "happy": "ankilope_celebrate",
    "streak": "ankilope_streak",
    "sad": "ankilope_sad",
    "hopeful": "ankilope_hopeful",
    "frozen": "ankilope_frozen",
    "neglected": "ankilope_neglected",
    "welcome": "ankilope_welcome",
    "review": "ankilope_study",
}

# Bluma's art for each pose she has: her core poses, exported as `bluma_*`.
BLUMA_POSES = {
    "face": "bluma_face",
    "asleep": "bluma_asleep",
    "happy": "bluma_happy",
    "streak": "bluma_streak",
    "sad": "bluma_sad",
    "hopeful": "bluma_hopeful",
    "frozen": "bluma_frozen",
    "neglected": "bluma_neglected",
}

# Anki-tan's art for each pose she has, as the pinned AnkiQuest-Art release exports it. Her face is
# a headshot and every other pose full body; welcome shows her hopeful master, as Art's manifest
# names it. Her other extensions fall back until they are drawn (AnkiQuest-Server#57).
ANKI_TAN_POSES = {
    "face": "anki_tan_face",
    "asleep": "anki_tan_asleep",
    "happy": "anki_tan_happy",
    "streak": "anki_tan_streak",
    "sad": "anki_tan_sad",
    "hopeful": "anki_tan_hopeful",
    "frozen": "anki_tan_frozen",
    "neglected": "anki_tan_neglected",
    "welcome": "anki_tan_hopeful",
}

# Each companion's art by pose.
_POSES = {AKI: AKI_POSES, ANKILOPE_ID: ANKILOPE, COW: BLUMA_POSES, ANKI_TAN: ANKI_TAN_POSES}


def current(profile, now_ms):
    """The profile while it still describes today; None once its study day has ended."""
    if not profile:
        return None
    ends = profile.get("day_ends_at") or 0
    return None if ends and ends <= now_ms else profile


def _reviews_today(profile):
    return int(((profile or {}).get("today") or {}).get("reviews") or 0)


def mood(chosen, decks_due, focus_due, profile, now_ms):
    """Today's line for the streak mood `chosen`; the collection, not the server, says whether
    cards are still due.

    `decks_due` lists every deck's due count, `focus_due` is the next deck's.
    """
    # A streak waiting for today, or kept by a freeze, comes before anything about the decks.
    if chosen == SAD:
        return WAITING
    if chosen in _FROZEN or chosen == MOOD_FREEZE:
        return FREEZE

    # Otherwise the decks decide: all done after real study, or cards still due.
    reviews = _reviews_today(current(profile, now_ms))
    if decks_due and all(due == 0 for due in decks_due) and reviews > 0:
        return CELEBRATE
    if focus_due > 0:
        return REVIEW
    if chosen == FIRE:
        return STREAK
    return WELCOME


# The mood for each stage after a freeze, and with a streak and no freeze; STARTED after a
# freeze shows the frozen level.
_THAWING_MOODS = {Stage.QUARTER: THAWING, Stage.HALF: HOPEFUL, Stage.THREE_QUARTERS: ALMOST}
_STREAK_MOODS = {Stage.STARTED: SAD, Stage.QUARTER: SAD, Stage.HALF: HOPEFUL, Stage.THREE_QUARTERS: ALMOST}


def streak_mood(state, reviews, stage, streak, frozen_days, goal, days_away=0, freezes=0,
                 day_left_ms=None, night=None, thresholds=None):
    """Today's streak mood for a day verdict `state` with `reviews` so far at `stage` toward the
    minimum, a `streak` of that many days and `frozen_days` frozen days in a row ending yesterday.
    `days_away` counts days without reviews in a row ending yesterday, `freezes` the freezes left,
    `day_left_ms` the time until the study day ends (None when unknown) and `night` the night
    rule's inputs (None outside it). `thresholds` (the debug menu's, `mood_debug.thresholds`) move
    the hopeful boundary and the frozen moods; the rest of the rule is pinned by
    tests/fixtures/streak_moods.json."""
    # Today counts, or the goal says the player did what they planned.
    if state == STUDIED or goal == Goal.REACHED:
        return FIRE
    if state == UNKNOWN:
        return MOOD_UNKNOWN

    # At night a comfortable companion sleeps until the player's usual first study time.
    if _sleeps(state, streak, night):
        return ASLEEP

    # A moved review threshold moves the hopeful boundary without changing the shared stages.
    stage = _hopeful_stage(reviews, stage, thresholds)

    # A protected day means a freeze kept at least yesterday, even without the heatmap.
    frozen = max(frozen_days, 1 if state == PROTECTED else 0)
    if frozen > 0:
        return _THAWING_MOODS.get(stage) or _frozen(frozen, thresholds)

    # Without a streak there is nothing to lose: any study is hopeful; days away show their level.
    if streak == 0:
        if reviews < (thresholds or {}).get("hopeful_reviews", 1):
            return _away(days_away)
        return ALMOST if stage == Stage.THREE_QUARTERS else HOPEFUL

    # A freeze about to keep the streak tonight is in effect.
    if reviews == 0 and freezes > 0 and day_left_ms is not None and day_left_ms <= FREEZE_WINDOW_MS:
        return MOOD_FREEZE
    return _STREAK_MOODS[stage]


def _sleeps(state, streak, night):
    """Whether the night rule puts a comfortable companion to sleep: no review yet, in the night
    window, the streak alive and yesterday counted."""
    if night is None or state != PENDING:
        return False
    return streak > 0 and night.yesterday == Yesterday.COUNTED and night.window()


def _away(days):
    """The mood for no streak and no review today after `days` away."""
    return next((mood for start, mood in AWAY_LEVELS if days >= start), ASLEEP)


def _hopeful_stage(reviews, stage, thresholds):
    """The stage a day counts as when a moved review threshold decides where hopeful starts, as
    the phone's mood rule does: reaching it is at least half way, falling short keeps the day
    before the halfway stage. An unmoved threshold leaves the stage alone, so the pinned
    streak-mood fixtures keep passing."""
    hopeful = (thresholds or {}).get("hopeful_reviews", 1)
    if hopeful == 1:
        return stage
    if reviews >= hopeful:
        return stage if stage.percent >= Stage.HALF.percent else Stage.HALF
    return stage if stage.percent <= Stage.QUARTER.percent else Stage.QUARTER


def _frozen(days, thresholds=None):
    """The frozen mood for `days` frozen days in a row; the third means that many or more.
    `thresholds` (the debug menu's, `mood_debug.thresholds`) can move where 2 and 3 start."""
    two = (thresholds or {}).get("frozen_2_days", 2)
    three = (thresholds or {}).get("frozen_3_days", 3)
    if days >= max(three, two + 1):
        return FROZEN_3
    if days >= two:
        return FROZEN_2
    return FROZEN_1


def _mood_pose_name(chosen, streak, thresholds=None):
    """The pose for a streak mood; a counted day burns by the streak's heat, from day one.
    `thresholds` (the debug menu's, `mood_debug.thresholds`) can move where the hotter poses
    start, so keep their order."""
    if chosen != FIRE:
        return _MOOD_POSE_NAMES[chosen]
    limits = HEAT
    if thresholds:
        hots = (
            (HEAT[0][1], thresholds.get("legend_days", HEAT[0][0])),
            (HEAT[1][1], thresholds.get("blazing_days", HEAT[1][0])),
            (HEAT[2][1], thresholds.get("hot_days", HEAT[2][0])),
            (HEAT[3][1], HEAT[3][0]),
        )
        limits = tuple((max(days, 1), aki) for aki, days in hots)
    heat = next((pose for days, pose in limits if streak >= days), limits[-1][1])
    return _AKI_PICTURES[heat]


def streak_pose(chosen, streak, thresholds=None):
    """Aki's picture for a streak mood with a streak of that many days."""
    return pose_art(AKI_POSES, _mood_pose_name(chosen, streak, thresholds))


def flame(chosen, streak=0):
    """The flame beside the streak number for a streak mood; asleep with a streak is the night's."""
    if chosen == ASLEEP and streak > 0:
        return NIGHT_FLAME
    return _FLAMES[chosen]


def frozen_run(heatmap):
    """The frozen days in a row ending yesterday in a profile's heatmap, whose last cell is today."""
    days = 0
    for cell in reversed((heatmap or [])[:-1]):
        if not (isinstance(cell, dict) and cell.get("frozen") is True):
            break
        days += 1
    return days


def away_run(heatmap):
    """Days without reviews in a row ending yesterday in a profile's heatmap, whose last cell is
    today; 0 when no earlier day was studied (a new player is not away)."""
    before = (heatmap or [])[:-1]
    for index in range(len(before) - 1, -1, -1):
        cell = before[index]
        if isinstance(cell, dict) and cell.get("state") != "none":
            return len(before) - 1 - index
    return 0


def yesterday(heatmap):
    """How yesterday ended, from a profile's heatmap whose last cell is today."""
    cells = heatmap or []
    if len(cells) < 2 or not isinstance(cells[-2], dict):
        return Yesterday.UNKNOWN
    cell = cells[-2]
    if cell.get("frozen") is True:
        return Yesterday.PROTECTED
    return Yesterday.COUNTED if cell.get("state") == "met" else Yesterday.MISSED


def day_state(view):
    """The verdict of a displayed profile's day (day_verdict._for_display)."""
    state = _DAY_STATES.get((view or {}).get("_day_status"), UNKNOWN)
    if state == PENDING and _reviews_today(view) > 0:
        return SHORT
    return state


def _streak(view):
    return int((view or {}).get("streak") or 0)


def _stage(view):
    """The displayed day's stage toward its minimum; older servers send whole minutes only."""
    today = (view or {}).get("today") or {}
    time_ms = today.get("time_ms")
    if time_ms is None:
        time_ms = int(today.get("minutes") or 0) * MINUTE_MS
    return Stage.of(int(time_ms or 0), int(today.get("streak_minutes") or 0))


def _freezes(view):
    """The freezes the player has left; 0 with freezes off."""
    if not view.get("freezes_enabled"):
        return 0
    return max(0, int(view.get("stored_freezes") or 0))


def _day_left_ms(view, now_ms):
    ends = view.get("day_ends_at")
    if not ends or now_ms is None:
        return None
    return int(ends) - now_ms


def today_mood(view, goal, night=None, now_ms=None, thresholds=None):
    """The displayed profile's streak mood: the one streak rule every surface uses. `night` holds
    the night rule's inputs (None outside it), `now_ms` the time for the day's end."""
    view = view or {}
    heatmap = view.get("heatmap")
    reviews, streak, frozen = _reviews_today(view), _streak(view), frozen_run(heatmap)
    return streak_mood(
        day_state(view), reviews, _stage(view), streak, frozen, goal,
        away_run(heatmap), _freezes(view), _day_left_ms(view, now_ms), night, thresholds,
    )


def today_pose(companion, view, goal, night=None, now_ms=None, thresholds=None):
    """`companion`'s pose for the displayed profile's day; None for no companion."""
    return mood_pose(companion, today_mood(view, goal, night, now_ms, thresholds), _streak(view))


def today_flame(view, goal, night=None, now_ms=None, thresholds=None):
    """The flame beside the displayed profile's streak number."""
    return flame(today_mood(view, goal, night, now_ms, thresholds), _streak(view))


def mood_pose(companion, chosen, streak, thresholds=None):
    """`companion`'s pose for a streak mood with a streak of that many days; None for no companion.

    It is resolved from the mood's pose, not from Aki's picture, because one of Aki's pictures
    stands for two poses (welcome for hopeful)."""
    if companion == NONE:
        return None
    return pose_art(companion_poses(companion), _mood_pose_name(chosen, streak, thresholds))


def forced_pose(companion, name):
    """`companion`'s pose for one of Aki's picture names, as the debug menu forces; None without
    a companion or when the companion cannot show that pose."""
    if companion == NONE:
        return None
    return pose_art(companion_poses(companion), name)


def mood_line(chosen, streak):
    """The companion tab's line for a mood, untranslated, and the values for its `%d`."""
    text = NIGHT_LINE if chosen == ASLEEP and streak > 0 else MOOD_LINES[chosen]
    if "%d" not in text:
        return text, ()

    # A reached goal burns before the server counts the day, so the streak is at least one.
    return text, (max(streak, 1),)


def art_owner(companion):
    """Whose art draws `companion`: its own. A companion this add-on has no art for, such as one
    a newer server knows, is drawn as Aki."""
    if companion == NONE or companion in _POSES:
        return companion
    return AKI


def companion_poses(companion):
    """`companion`'s art by pose (`art_owner`'s); call it with a companion, not "none"."""
    return _POSES[art_owner(companion)]


def face(companion):
    """The file name of `companion`'s face, its only headshot; None for no companion."""
    if companion == NONE:
        return None
    return companion_poses(companion)["face"]


def pose_art(art, pose):
    """The picture in `art` (pose to picture) for `pose`, or for its nearest fallback: an extension's
    (`POSE_FALLBACKS`) or a picture's (`PICTURE_FALLBACKS`), then a core pose's while it is not
    drawn (`CORE_FALLBACKS`)."""
    while pose not in art:
        pose = POSE_FALLBACKS.get(pose) or PICTURE_FALLBACKS.get(pose) or CORE_FALLBACKS[pose]
    return art[pose]


def companion_pose(companion, aki):
    """`companion`'s version of Aki's picture `aki`, by the pose it shows; None for no companion."""
    if companion == NONE:
        return None
    owner = art_owner(companion)
    if owner == AKI:
        return aki

    # A pose shows the companion's own; a scene only Aki has shows the pose poses.json names.
    pose = _AKI_PICTURES.get(aki)
    if pose is None:
        scene = aki[len(_AKI_PREFIX):] if aki.startswith(_AKI_PREFIX) else aki
        pose = PICTURE_FALLBACKS.get(scene, _UNKNOWN_PICTURE_POSE)
    return pose_art(_POSES[owner], pose)


def preview(companion):
    """The poses `companion`'s picker card shows, by `PREVIEW_POSES`, each once; none for no
    companion."""
    found = []
    for aki in PREVIEW_POSES:
        pose = companion_pose(companion, aki)
        if pose is not None and pose not in found:
            found.append(pose)
    return found


def art(companion, chosen):
    """The file name, without folder or extension, of `companion`'s art for a mood; None for no companion."""
    return companion_pose(companion, "aki_" + chosen if chosen in MOODS else "aki_welcome")


def message(companion, chosen, streak):
    """The untranslated line (None while reviewing) and its format values. The welcome
    names Aki, so other companions get a plainer one."""
    if chosen == REVIEW:
        return None, ()
    if chosen == WAITING:
        # A sad streak is at least one day long, so the one-day form is the only singular.
        one, other = WAITING_LINES
        return (one, ()) if streak == 1 else (other, (streak,))
    if chosen == WELCOME and companion != AKI:
        return COMPANION_WELCOME, ()
    return MESSAGES.get(chosen, MESSAGES[WELCOME]), ()
