"""The hidden debug menu's override of today's mood and pose, and its local thresholds.

A modifier-click on the version label in the add-on's settings opens the menu. The choice is
kept in this add-on's config only (`debug_mood`), never sent to the server: no upload touches
the key and the shared-settings sync leaves unknown local keys alone. The thresholds below
move the hopeful review count and the poses' day limits the same way; `moods` owns the defaults
so the pinned streak-mood fixtures do not.
"""

from enum import Enum, auto
from . import moods

# The thresholds the debug menu can move, in the Android menu's order, with the values the
# rules use (the reviews that make today hopeful, the day each streak pose starts at, and the
# frozen days in a row each frozen mood needs). `moods` owns the same numbers for computed
# moods; the keys name them for the menu.
THRESHOLDS = ("hopeful_reviews", "frozen_2_days", "frozen_3_days", "hot_days", "blazing_days", "legend_days")
DEFAULT_THRESHOLDS = {
    "hopeful_reviews": 1,
    "hot_days": 7,
    "blazing_days": 30,
    "legend_days": 100,
    "frozen_2_days": 2,
    "frozen_3_days": 3,
}

# A mood override holds one of the fixture's streak moods; a pose override, one of the pose
# names every companion resolves through `moods` (its core poses and their extensions).
Moods = moods.STREAK_MOODS
Poses = moods.CORE_POSES + tuple(sorted(moods.POSE_FALLBACKS))


class Override(Enum):
    """What the menu replaces today with, as one state. AUTO shows what the rules computed;
    MOOD forces one streak mood everywhere; POSE forces one pose, leaving the mood alone."""

    AUTO = auto()
    MOOD = auto()
    POSE = auto()

    @classmethod
    def read(cls, config):
        """The override state in `config`, refusing anything but the known kinds and values."""
        stored = (config or {}).get("debug_override")
        if not stored:
            return cls.AUTO, None
        kind, _, value = stored.partition(":")
        if kind == "mood":
            return read_choice(cls.MOOD, value, Moods, "mood")
        if kind == "pose":
            return read_choice(cls.POSE, value, Poses, "pose")
        return cls.AUTO, None


def read_choice(kind, value, choices, name):
    """"`kind` of a listed `value`, or AUTO when the stored value is not one any more."""
    if value not in choices:
        return Override.AUTO, None
    return kind, value



def stored(kind, value=None):
    """The config entry for `kind`: an empty one clears the override to AUTO."""
    if kind is Override.AUTO or value is None:
        return ""
    if kind is Override.MOOD:
        return "mood:%s" % value
    return "pose:%s" % value


def mood(computed, kind, value):
    """Today's mood with the override applied: a forced mood replaces the computed one."""
    return value if kind is Override.MOOD else computed


def pose(companion, computed_mood, streak, kind, value):
    """`companion`'s pose with the override applied: a forced mood picks its own pose, and a
    forced pose replaces whatever the mood picked."""
    if kind is Override.POSE:
        return moods.forced_pose(companion, value)
    return moods.mood_pose(companion, mood(computed_mood, kind, value), streak)


def flame(computed_mood, kind, value):
    """The flame beside the streak number, following the shown mood."""
    return moods.flame(mood(computed_mood, kind, value))


def marker(kind):
    """The line marking an override on the surfaces it changes; None without one.
    The wording matches the Android app's debug marker."""
    return "Debug override" if kind is not Override.AUTO else None


def ordered(limits):
    """Whether the thresholds keep the order the moods need, as the Android menu checks:
    one review or more for hopeful, each streak pose after the one before it, and frozen 3
    past frozen 2."""
    return (limits["hopeful_reviews"] >= 1
            and 2 <= limits["frozen_2_days"] < limits["frozen_3_days"]
            and 2 <= limits["hot_days"] < limits["blazing_days"] < limits["legend_days"])


def thresholds(config):
    """The thresholds the moods use, from `config` where the menu moved them; whole numbers
    one and up, else that threshold keeps its rule value."""
    moved = {}
    stored = (config or {}).get("debug_thresholds") or {}
    for name in THRESHOLDS:
        wanted = stored.get(name)
        if isinstance(wanted, int) and not isinstance(wanted, bool) and wanted >= 1:
            moved[name] = wanted
        else:
            moved[name] = DEFAULT_THRESHOLDS[name]
    return moved


def thresholds_stored(values):
    """The config entry for the thresholds the menu set, dropping ones left at their rule."""
    stored = {}
    for name in THRESHOLDS:
        wanted = values.get(name, DEFAULT_THRESHOLDS[name])
        if wanted != DEFAULT_THRESHOLDS[name]:
            stored[name] = wanted
    return stored
