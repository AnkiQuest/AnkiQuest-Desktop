"""Companions earned at milestones: Ankilope at a level, the cow by hours of study.

The server decides and keeps every unlock; the add-on shows what `GET /api/unlocks/{user}`
answers. The conditions are defined once in tests/fixtures/companion_unlock.json, which the tests
check these texts against. The fixture's tap rule (`Taps`) is for Anki-tan's chibi, which has no
art yet, so nothing taps yet."""

from enum import Enum, auto

from . import moods

FEATURE = "companion_unlocks"

# Companions earned at a milestone, in the picker's order.
EARNED = (moods.ANKILOPE_ID, moods.COW)

# Earned companions every player could choose before milestones. A server from then lists no
# progress, so these stay free there; the others stay hidden until unlocked.
OFFERED_BEFORE = (moods.ANKILOPE_ID,)

# What each milestone counts, as the fixture names it.
LEVEL, STUDY_HOURS = "level", "study_hours"

TAPS = 9
MAX_GAP_MS = 2000


class Choice(Enum):
    """How the picker offers a companion."""
    FREE = auto()
    UNLOCKED = auto()
    # Shown greyed with its condition and progress; it cannot be chosen.
    LOCKED = auto()
    # Secret until earned, or unknown to an older server.
    HIDDEN = auto()


class Found:
    """The server's answer: what the player has unlocked, and the progress toward each locked
    companion that shows before it is earned, by companion."""

    def __init__(self, unlocks=(), progress=None):
        self.unlocks = frozenset(unlocks)
        self.progress = dict(progress or {})


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _progress(entry):
    """One progress entry, or None when it is not one this add-on can show."""
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str):
        return None
    value, goal = _number(entry.get("value")), _number(entry.get("goal"))
    if value is None or goal is None:
        return None
    return {"kind": entry["kind"], "value": value, "goal": goal}


def parse(answer):
    """The `GET /api/unlocks/{user}` answer, leaving out what it cannot read."""
    if not isinstance(answer, dict):
        return Found()
    unlocks = [unlock for unlock in answer.get("unlocks") or () if isinstance(unlock, str)]
    listed = answer.get("progress") if isinstance(answer.get("progress"), dict) else {}
    progress = {}
    for companion, entry in listed.items():
        found = _progress(entry)
        if found is not None:
            progress[companion] = found
    return Found(unlocks, progress)


def fetch(api, features):
    """The server's unlocks and progress; nothing unlocked for a server without unlocks. Runs
    in the background."""
    if FEATURE not in features:
        return Found()
    return parse(api.unlocks())


def choice(companion, found, current):
    """How the picker offers `companion` to a player whose companion is `current`, given the
    server's `found` (None until it answers)."""
    if companion not in EARNED:
        return Choice.FREE
    if companion == current or (found is not None and companion in found.unlocks):
        return Choice.UNLOCKED
    if found is not None and companion in found.progress:
        return Choice.LOCKED
    return Choice.FREE if companion in OFFERED_BEFORE and found is not None else Choice.HIDDEN


def condition(progress, tr):
    """How a locked companion is earned, such as "Reach level 30"; None for a kind this add-on
    does not know."""
    if progress["kind"] == LEVEL:
        return tr("Reach level %d") % progress["goal"]
    if progress["kind"] == STUDY_HOURS:
        return tr("Study for %d hours in total") % progress["goal"]
    return None


def reached(progress, tr):
    """How far the player is, such as "Level 3 of 30"; None for a kind this add-on does not
    know."""
    if progress["kind"] == LEVEL:
        return tr("Level %d of %d") % (progress["value"], progress["goal"])
    if progress["kind"] == STUDY_HOURS:
        return tr("%d of %d hours") % (progress["value"], progress["goal"])
    return None


class Taps:
    """Counts taps on `target` in a row; a tap elsewhere or a long gap starts again."""

    def __init__(self, target):
        self._target = target
        self._run = 0
        self._last_ms = None

    def tap(self, choice, at_ms):
        """Records a tap on `choice`; True on the tap that completes the run."""
        if choice != self._target:
            self._run, self._last_ms = 0, None
            return False

        # A late tap is the first of a new run.
        late = self._last_ms is not None and at_ms - self._last_ms > MAX_GAP_MS
        self._run = 1 if late else self._run + 1
        self._last_ms = at_ms
        if self._run < TAPS:
            return False
        self._run, self._last_ms = 0, None
        return True
