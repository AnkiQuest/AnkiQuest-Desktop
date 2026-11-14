"""The companion's mood for today, and its artwork, chosen like the phone app's Aki.

Two rules live here. `streak_mood` picks the pose from today's streak, as the phone's
AnkiquestMood does, pinned by tests/fixtures/streak_moods.json. `mood` picks the encouraging
line from the collection's due cards.
"""

from enum import Enum, auto

WELCOME, REVIEW, CELEBRATE, STREAK, FREEZE, WINNER = "welcome", "review", "celebrate", "streak", "freeze", "winner"

MESSAGES = {
    WELCOME: "Aki is here to help. One card, one small step.",
    REVIEW: "A small step starts with one card.",
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

# The pose for each mood but fire. Interim poses stand in until sad, hopeful and frozen art
# exists (#88): at_risk is the most worried, welcome smiles with a card, freeze_used has snow.
_MOOD_POSES = {
    MOOD_UNKNOWN: "aki_face",
    ASLEEP: "aki_sleeping",
    SAD: "aki_at_risk",
    FROZEN_1: "aki_freeze_used",
    FROZEN_2: "aki_freeze",
    FROZEN_3: "aki_freeze_used",
    HOPEFUL: "aki_welcome",
}

# A counted day's pose by heat: the first streak length each pose starts at, hottest first.
HEAT = ((100, "aki_streak_legend"), (30, "aki_streak_blazing"), (7, "aki_streak_hot"), (1, "aki_streak"))


class Goal(Enum):
    """Whether today's daily goal is reached."""
    OPEN = auto()
    REACHED = auto()


# The companions in the picker's order, and the names it shows; "none" is named by the picker.
AKI, ANKILOPE_ID, COW, NONE = "aki", "ankilope", "cow", "none"
NAMES = {AKI: "Aki", ANKILOPE_ID: "Ankilope", COW: "Bluma"}

# The Aki poses each picker card previews, in the phone's order: face, fire, sad.
PREVIEW_POSES = ("aki_face", "aki_streak", "aki_at_risk")

# How far the cow's art is hue-rotated, as CSS hue-rotate() turns it; see `art_owner`.
COW_HUE_DEGREES = 250

# Ankilope's version of each Aki pose, as the phone's AnkiquestCompanion maps them.
ANKILOPE = {
    "aki_face": "ankilope_face",
    "aki_welcome": "ankilope_welcome",
    "aki_sleeping": "ankilope_welcome",
    "aki_celebrate": "ankilope_celebrate",
    "aki_winner": "ankilope_celebrate",
}


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


def streak_pose(chosen, streak):
    """Aki's pose for a streak mood; a counted day burns by the streak's heat, from day one."""
    if chosen != FIRE:
        return _MOOD_POSES[chosen]
    return next((pose for days, pose in HEAT if streak >= days), HEAT[-1][1])


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


def today_pose(view, goal):
    """Aki's pose for the displayed profile's day: the one streak rule every surface uses."""
    view = view or {}
    streak = int(view.get("streak") or 0)
    chosen = streak_mood(day_state(view), _reviews_today(view), streak, frozen_run(view.get("heatmap")), goal)
    return streak_pose(chosen, streak)


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


def companion_pose(companion, aki):
    """`companion`'s version of the Aki pose `aki`; None for no companion."""
    if companion == NONE:
        return None
    if art_owner(companion) == ANKILOPE_ID:
        return ANKILOPE.get(aki, "ankilope_study")
    return aki


def preview(companion):
    """The poses `companion`'s picker card shows, by `PREVIEW_POSES`, each once; none for no
    companion. Ankilope has fewer poses, so its card shows fewer."""
    found = []
    for aki in PREVIEW_POSES:
        pose = companion_pose(companion, aki)
        if pose is not None and pose not in found:
            found.append(pose)
    return found


def art(companion, chosen):
    """The file name, without folder or extension, of `companion`'s art for a mood; None for no companion."""
    return companion_pose(companion, "aki_" + chosen if chosen in MESSAGES else "aki_welcome")


def message(companion, chosen):
    """The mood line; the welcome names Aki, so other companions get a plainer one."""
    if chosen == WELCOME and companion != AKI:
        return COMPANION_WELCOME
    return MESSAGES.get(chosen, MESSAGES[WELCOME])
