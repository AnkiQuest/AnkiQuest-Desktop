"""Companions earned at milestones: Ankilope at a level, the cow by hours of study.

The server decides and keeps every unlock; the add-on shows what `GET /api/unlocks/{user}`
answers. The conditions are defined once in tests/fixtures/companion_unlock.json, which the tests
check these texts against. A chibi is an Easter egg: tapping its unlocked base's picture by the
fixture's tap rule (`Egg`) finds it, and the add-on then asks the server for it. Anki-tan and her
chibi have no art yet, so nothing taps yet."""

from enum import Enum, auto

from . import moods

# Companions earned at a milestone, in the picker's order.
EARNED = (moods.ANKILOPE_ID, moods.COW)

# What each milestone counts, as the fixture names it.
LEVEL, STUDY_HOURS = "level", "study_hours"

TAPS = 9
MAX_GAP_MS = 2000

# Each chibi by its base, the companion whose picture is tapped; the fixture's `requires`.
CHIBIS = {"anki_tan": "anki_tan_chibi"}

# The tap of a run from which the hint shows how many taps are still needed.
HINT_FROM = 4


class Choice(Enum):
    """How the picker offers a companion."""
    FREE = auto()
    UNLOCKED = auto()
    # Shown greyed with its condition and progress; it cannot be chosen.
    LOCKED = auto()
    # Secret until earned, or not yet answered by the server.
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


def fetch(api):
    """The server's unlocks and progress. Runs in the background."""
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
    return Choice.HIDDEN


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
    """Counts taps on `target` in a row; a tap elsewhere, a long gap or an earlier time starts
    again."""

    def __init__(self, target):
        self._target = target
        # Taps on `target` so far in this run.
        self._run = 0
        self._last_ms = None

    def tap(self, choice, at_ms):
        """Records a tap on `choice`; True on the tap that completes the run."""
        if choice != self._target:
            self._run, self._last_ms = 0, None
            return False

        # A late or earlier tap is the first of a new run.
        quick = self._last_ms is not None and 0 <= at_ms - self._last_ms <= MAX_GAP_MS
        self._run = self._run + 1 if quick else 1
        self._last_ms = at_ms
        if self._run < TAPS:
            return False
        self._run, self._last_ms = 0, None
        return True


def chibi_of(companion, unlocks):
    """The chibi tapping `companion` finds; None when it has none or is not in `unlocks`."""
    chibi = CHIBIS.get(companion)
    if chibi is None or companion not in unlocks:
        return None
    return chibi


def hint(count, tr):
    """What a run of `count` taps shows, such as "You are 5 taps away from chibi"; None before
    `HINT_FROM` and on the last tap, which finds the chibi instead."""
    left = TAPS - count
    if count < HINT_FROM or left <= 0:
        return None
    if left == 1:
        return tr("You are 1 tap away from chibi")
    return tr("You are %d taps away from chibi") % left


class Tapped:
    """What one tap on a companion's picture shows: the `hint`, or the `chibi` it found."""

    def __init__(self, hint=None, chibi=None):
        self.hint = hint
        self.chibi = chibi


class Egg:
    """Counts taps on companions' pictures toward their chibis, given the server's `unlocks`.
    Only a base that has a chibi and is unlocked counts; a tap on any other picture starts
    again."""

    def __init__(self, unlocks):
        self._unlocks = frozenset(unlocks)
        self._taps = None

    def tap(self, companion, at_ms, tr):
        chibi = chibi_of(companion, self._unlocks)
        if chibi is None:
            self._taps = None
            return Tapped()
        if self._taps is None or self._taps._target != companion:
            self._taps = Taps(companion)
        if self._taps.tap(companion, at_ms):
            return Tapped(chibi=chibi)
        return Tapped(hint=hint(self._taps._run, tr))
