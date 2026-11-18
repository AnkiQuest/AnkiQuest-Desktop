"""The reveal that plays when a companion joins: its phases, timing and beam colour.

A card falls and lands with a glow, a beam in the companion's colour rises, particles burst and
the companion appears with "Choose", "Share" and "Later". With reduced motion the companion
only fades in. A tap skips to the companion. It plays for an unlock moment no device has read
yet; the moment card shows it everywhere else (#271). reveal_ui draws it."""

from enum import Enum, auto

from . import moments, moods

# Companions without art yet, as tests/fixtures/companion_unlock.json names them.
ANKI_TAN, ANKI_TAN_CHIBI = "anki_tan", "anki_tan_chibi"
QUEST_CHAN, QUEST_CHAN_CHIBI = "quest_chan", "quest_chan_chibi"
LEECH_KUN = "leech_kun"


class Motion(Enum):
    """Whether the player's Anki asks for reduced motion."""
    FULL = auto()
    REDUCED = auto()


class Phase(Enum):
    FALLING = auto()
    BEAM = auto()
    BURST = auto()
    # Reduced motion: the companion fades in.
    FADING = auto()
    # The companion with its name and buttons, until the player closes it.
    SHOWN = auto()
    CLOSED = auto()


class Beam(Enum):
    """The beam's colour, which shows how rare the companion is."""
    WHITE = auto()
    BLUE = auto()
    PURPLE = auto()
    GOLD = auto()
    RAINBOW = auto()


# Each beam's colours as RGB, left to right across the beam; one colour is a plain beam.
COLOURS = {
    Beam.WHITE: ((255, 255, 255),),
    Beam.BLUE: ((90, 160, 255),),
    Beam.PURPLE: ((180, 110, 255),),
    Beam.GOLD: ((255, 200, 60),),
    Beam.RAINBOW: ((255, 80, 80), (255, 200, 60), (90, 220, 120), (90, 160, 255), (180, 110, 255)),
}

BEAMS = {
    moods.AKI: Beam.WHITE,
    moods.ANKILOPE_ID: Beam.BLUE,
    moods.COW: Beam.PURPLE,
    ANKI_TAN: Beam.GOLD,
    ANKI_TAN_CHIBI: Beam.RAINBOW,
    QUEST_CHAN: Beam.GOLD,
    QUEST_CHAN_CHIBI: Beam.RAINBOW,
    LEECH_KUN: Beam.GOLD,
}

# How long each animated phase lasts, and the phase after it.
DURATION_MS = {Phase.FALLING: 1000, Phase.BEAM: 1400, Phase.BURST: 1100, Phase.FADING: 600}
_NEXT = {Phase.FALLING: Phase.BEAM, Phase.BEAM: Phase.BURST, Phase.BURST: Phase.SHOWN, Phase.FADING: Phase.SHOWN}
_FIRST = {Motion.FULL: Phase.FALLING, Motion.REDUCED: Phase.FADING}


class Reveal:
    """One reveal's phase. `advance` when a phase's time is up, `skip` on a tap, `close` when
    the window goes."""

    def __init__(self, motion):
        self.phase = _FIRST[motion]

    def duration_ms(self):
        """How long the current phase animates; None once the companion shows."""
        return DURATION_MS.get(self.phase)

    def advance(self):
        self.phase = _NEXT.get(self.phase, self.phase)

    def skip(self):
        if self.phase in _NEXT:
            self.phase = Phase.SHOWN

    def close(self):
        self.phase = Phase.CLOSED


def length_ms(motion):
    """The whole animation's length before the companion shows."""
    phase, total = _FIRST[motion], 0
    while phase in _NEXT:
        total += DURATION_MS[phase]
        phase = _NEXT[phase]
    return total


def beam(companion):
    return BEAMS.get(companion, Beam.WHITE)


def due(item):
    """Whether a moment plays the reveal here: an unlock of a known companion whose
    notification no device has read yet."""
    return moments.joined(item) is not None and item.get("notice") is not None and item.get("unread") is True
