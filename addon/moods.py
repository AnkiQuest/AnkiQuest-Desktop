"""The companion's mood for today, and its artwork, chosen like the phone app's Aki.

Two rules live here. `streak_mood` picks the pose, and `flame` the flame beside the streak
number, from today's streak, as the phone's AnkiquestMood does, pinned by
tests/fixtures/streak_moods.json. `mood` picks the encouraging line from the collection's due
cards.
"""

from enum import Enum, auto

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

# Today's day verdict, as the fixture names it.
STUDIED, PROTECTED, SHORT, PENDING, UNKNOWN = "studied", "protected", "short", "pending", "unknown"

# The displayed day's `_day_status` (day_verdict._for_display) to its verdict; pending splits by reviews.
_DAY_STATES = {"met": STUDIED, "syncing": STUDIED, "protected": PROTECTED, "pending": PENDING}

# Aki's streak moods, as the phone names them.
STREAK_MOODS = ("unknown", "asleep", "sad", "frozen_1", "frozen_2", "frozen_3", "hopeful", "fire")
(MOOD_UNKNOWN, ASLEEP, SAD, FROZEN_1, FROZEN_2, FROZEN_3, HOPEFUL, FIRE) = STREAK_MOODS

# The companion tab's line for each mood, saying why; `%d` is the streak.
MOOD_LINES = {
    MOOD_UNKNOWN: "Waiting for today’s study to sync.",
    ASLEEP: "Asleep: study a card to start a streak.",
    SAD: "Sad: your %d-day streak is waiting for today’s study.",
    FROZEN_1: "Frozen: a freeze kept your streak. Study today to thaw.",
    FROZEN_2: "Frozen for 2 days: study today to thaw.",
    FROZEN_3: "Frozen for 3 days or more: study today to thaw.",
    HOPEFUL: "Hopeful: a little more study and today counts.",
    FIRE: "On fire: today counts for your %d-day streak.",
}

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
    SAD: Flame.UNLIT,
    HOPEFUL: Flame.UNLIT,
    FROZEN_1: Flame.ICY,
    FROZEN_2: Flame.ICY,
    FROZEN_3: Flame.ICY,
    FIRE: Flame.LIT,
}


class Goal(Enum):
    """Whether today's daily goal is reached."""
    OPEN = auto()
    REACHED = auto()


# The companions in the picker's order, and the names it shows; "none" is named by the picker.
AKI, ANKILOPE_ID, COW, NONE = "aki", "ankilope", "cow", "none"
NAMES = {AKI: "Aki", ANKILOPE_ID: "Ankilope", COW: "Bluma"}

# The Aki poses each picker card previews, in the phone's order: face, fire, sad.
PREVIEW_POSES = ("aki_face", "aki_streak", "aki_sad")

# How far the cow's art is hue-rotated, as CSS hue-rotate() turns it; see `art_owner`.
COW_HUE_DEGREES = 250

# The poses tests/fixtures/companion_poses.json names: the core poses every companion has, and
# the pose each extension falls back to where a companion has no art for it.
CORE_POSES = ("face", "asleep", "happy", "streak", "sad", "hopeful", "frozen", "neglected")
POSE_FALLBACKS = {
    "streak_hot": "streak",
    "streak_blazing": "streak_hot",
    "streak_legend": "streak_blazing",
    "streak_milestone": "streak_legend",
    "frozen_2": "frozen",
    "frozen_3": "frozen_2",
    "welcome": "happy",
    "review": "happy",
    "hurt": "sad",
    "abandoned": "neglected",
    "dead": "neglected",
    "leech_defeated": "happy",
    "winner": "happy",
}

# The pose each of Aki's pictures shows, so that other companions show theirs.
_AKI_PICTURES = {
    "aki_face": "face",
    "aki_sleeping": "asleep",
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

# The pose each streak mood shows; fire burns by heat (`HEAT`).
_MOOD_POSE_NAMES = {
    MOOD_UNKNOWN: "face",
    ASLEEP: "asleep",
    SAD: "sad",
    FROZEN_1: "frozen",
    FROZEN_2: "frozen_2",
    FROZEN_3: "frozen_3",
    HOPEFUL: "hopeful",
}

# Aki's art for each pose she has, as the phone's AnkiquestCompanion maps them. She has no frozen 2
# or 3 art: those show her frozen pose.
AKI_POSES = {
    "face": "aki_face",
    "asleep": "aki_sleeping",
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

# Ankilope's art for each pose she has, as the phone's AnkiquestCompanion maps them. On fire she
# studies until her on-fire art exists (hill, 2026-11-18).
ANKILOPE = {
    "face": "ankilope_face",
    "asleep": "ankilope_sleeping",
    "happy": "ankilope_celebrate",
    "streak": "ankilope_study",
    "sad": "ankilope_sad",
    "hopeful": "ankilope_hopeful",
    "frozen": "ankilope_frozen",
    "neglected": "ankilope_neglected",
    "welcome": "ankilope_welcome",
    "review": "ankilope_study",
}

# Ankilope's picture for Aki's scenes she has no art for.
_ANKILOPE_SCENE = "ankilope_study"


def current(profile, now_ms):
    """The profile while it still describes today; None once its study day has ended."""
    if not profile:
        return None
    ends = profile.get("day_ends_at") or 0
    return None if ends and ends <= now_ms else profile


def _reviews_today(profile):
    return int(((profile or {}).get("today") or {}).get("reviews") or 0)


def mood(decks_due, focus_due, profile, now_ms):
    """Today's mood; the collection, not the server, says whether cards are still due.

    `decks_due` lists every deck's due count, `focus_due` is the next deck's.
    """
    today = current(profile, now_ms)
    reviews = _reviews_today(today)
    state = (today or {}).get("streak_state")
    if state == "protected" and reviews == 0:
        return FREEZE
    if decks_due and all(due == 0 for due in decks_due) and reviews > 0:
        return CELEBRATE
    if focus_due > 0:
        return REVIEW
    if state == "studied" and reviews > 0:
        return STREAK
    return WELCOME


def streak_mood(state, reviews, streak, frozen_days, goal):
    """Today's streak mood for a day verdict `state` with `reviews` so far, a `streak` of that many
    days and `frozen_days` frozen days in a row ending yesterday."""
    # Today counts, or the goal says the player did what they planned.
    if state == STUDIED or goal == Goal.REACHED:
        return FIRE
    if state == UNKNOWN:
        return MOOD_UNKNOWN
    if reviews > 0:
        return HOPEFUL

    # A protected day means a freeze kept at least yesterday, even without the heatmap.
    frozen = max(frozen_days, 1 if state == PROTECTED else 0)
    if frozen >= 3:
        return FROZEN_3
    if frozen == 2:
        return FROZEN_2
    if frozen == 1:
        return FROZEN_1
    return ASLEEP if streak == 0 else SAD


def _mood_pose_name(chosen, streak):
    """The pose for a streak mood; a counted day burns by the streak's heat, from day one."""
    if chosen != FIRE:
        return _MOOD_POSE_NAMES[chosen]
    heat = next((pose for days, pose in HEAT if streak >= days), HEAT[-1][1])
    return _AKI_PICTURES[heat]


def streak_pose(chosen, streak):
    """Aki's picture for a streak mood with a streak of that many days."""
    return pose_art(AKI_POSES, _mood_pose_name(chosen, streak))


def flame(chosen):
    """The flame beside the streak number for a streak mood."""
    return _FLAMES[chosen]


def frozen_run(heatmap):
    """The frozen days in a row ending yesterday in a profile's heatmap, whose last cell is today."""
    days = 0
    for cell in reversed((heatmap or [])[:-1]):
        if not (isinstance(cell, dict) and cell.get("frozen") is True):
            break
        days += 1
    return days


def day_state(view):
    """The verdict of a displayed profile's day (day_verdict._for_display)."""
    state = _DAY_STATES.get((view or {}).get("_day_status"), UNKNOWN)
    if state == PENDING and _reviews_today(view) > 0:
        return SHORT
    return state


def _streak(view):
    return int((view or {}).get("streak") or 0)


def today_mood(view, goal):
    """The displayed profile's streak mood: the one streak rule every surface uses."""
    view = view or {}
    return streak_mood(day_state(view), _reviews_today(view), _streak(view), frozen_run(view.get("heatmap")), goal)


def today_pose(companion, view, goal):
    """`companion`'s pose for the displayed profile's day; None for no companion."""
    return mood_pose(companion, today_mood(view, goal), _streak(view))


def today_flame(view, goal):
    """The flame beside the displayed profile's streak number."""
    return flame(today_mood(view, goal))


def mood_line(chosen, streak):
    """The companion tab's line for a mood, untranslated, and the values for its `%d`."""
    text = MOOD_LINES[chosen]
    if "%d" not in text:
        return text, ()

    # A reached goal burns before the server counts the day, so the streak is at least one.
    return text, (max(streak, 1),)


def art_owner(companion):
    """Whose art draws `companion`. The cow has none yet (#88): it is Ankilope's, turned by
    `hue_degrees`."""
    return ANKILOPE_ID if companion == COW else companion


def hue_degrees(companion):
    """How far `companion`'s art is hue-rotated: only the cow's, until it has its own (#88)."""
    return COW_HUE_DEGREES if companion == COW else 0


def css_filter(companion):
    """The CSS filter for `companion`'s art in web views; None when it needs none."""
    degrees = hue_degrees(companion)
    return "hue-rotate(%ddeg)" % degrees if degrees else None


def pose_art(art, pose):
    """The picture in `art` (pose to picture) for `pose`, or for its nearest fallback."""
    while pose not in art:
        pose = POSE_FALLBACKS[pose]
    return art[pose]


def companion_pose(companion, aki):
    """`companion`'s version of Aki's picture `aki`, by the pose it shows; None for no companion."""
    if companion == NONE:
        return None
    if art_owner(companion) != ANKILOPE_ID:
        return aki
    pose = _AKI_PICTURES.get(aki)
    if pose is None:
        return _ANKILOPE_SCENE
    return pose_art(ANKILOPE, pose)


def mood_pose(companion, chosen, streak):
    """`companion`'s pose for a streak mood with a streak of that many days; None for no companion.

    It is resolved from the mood's pose, not from Aki's picture, because one of Aki's pictures
    stands for two poses (welcome for hopeful)."""
    if companion == NONE:
        return None
    art = ANKILOPE if art_owner(companion) == ANKILOPE_ID else AKI_POSES
    return pose_art(art, _mood_pose_name(chosen, streak))


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


def message(companion, chosen):
    """The mood line, or None for a mood without one; the welcome names Aki, so other
    companions get a plainer one."""
    if chosen == REVIEW:
        return None
    if chosen == WELCOME and companion != AKI:
        return COMPANION_WELCOME
    return MESSAGES.get(chosen, MESSAGES[WELCOME])
