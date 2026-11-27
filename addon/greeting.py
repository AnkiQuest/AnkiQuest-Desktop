"""Aki introduces herself once per computer, on the first profile open after Anki's own dialogs.

The state is kept in Anki's machine-wide profile manager data: not in a profile, not in the
add-on's synced settings and never on the server. Android keeps the same state per device."""

from enum import Enum, auto

from aqt.qt import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, Qt

from . import companion_art
from .language import tr

KEY = "ankiquestGreeting"
IMAGE = "aki_welcome"
IMAGE_SIZE = 160


class State(Enum):
    """Whether this computer still owes the player Aki's greeting."""
    PENDING = "PENDING"
    SHOWN = "SHOWN"


class Account(Enum):
    SIGNED_IN = auto()
    SIGNED_OUT = auto()


class Choice(Enum):
    """What the player did with the greeting."""
    SIGN_IN = auto()
    # Later, Let’s study, or the window closed another way.
    DONE = auto()


def state(meta):
    """The stored state; a computer without one, or with an unknown one, owes the greeting."""
    try:
        return State(meta.get(KEY))
    except ValueError:
        return State.PENDING


def remember(meta, value):
    meta[KEY] = value.value


def _plain(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def ask(parent, account):
    """Shows the greeting until the player closes it. Always Aki, whatever the companion
    setting: the greeting introduces her."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("AnkiQuest")
    dialog.setWindowIcon(companion_art.icon("aki"))
    layout = QVBoxLayout(dialog)

    # Picture, title and text, in Android's order.
    image = QLabel()
    image.setPixmap(companion_art.pixmap(companion_art.pose_path(IMAGE), IMAGE_SIZE))
    image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    image.setAccessibleName(tr("Aki waving hello"))
    layout.addWidget(image)
    title = _plain(tr("Hi, I’m Aki!"))
    font = title.font()
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.4)
    title.setFont(font)
    layout.addWidget(title)
    layout.addWidget(_plain(tr("AnkiQuest adds streaks, friends and leaderboards to Anki. I’ll keep you company while you study.")))

    # Signed-out players are offered the sign-in; signed-in players go straight to their decks.
    row = QHBoxLayout()
    row.addStretch(1)
    if account is Account.SIGNED_OUT:
        later = QPushButton(tr("Later"))
        later.clicked.connect(dialog.reject)
        sign_in = QPushButton(tr("Sign in"))
        sign_in.setDefault(True)
        sign_in.clicked.connect(dialog.accept)
        row.addWidget(later)
        row.addWidget(sign_in)
    else:
        study = QPushButton(tr("Let’s study"))
        study.setDefault(True)
        study.clicked.connect(dialog.accept)
        row.addWidget(study)
    layout.addLayout(row)

    # Only Sign in accepts a signed-out greeting.
    accepted = dialog.exec()
    return Choice.SIGN_IN if accepted and account is Account.SIGNED_OUT else Choice.DONE
