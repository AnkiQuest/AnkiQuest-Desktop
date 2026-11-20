"""The companion tab: the chosen companion in today's mood, and the picker, a card per
companion with a preview of its poses.

Companions earned at a milestone show as a greyed silhouette with their condition and progress
until the server has unlocked them (companion_unlock); secret ones stay hidden. Settings,
Tools > AnkiQuest > Study companion and the companion in the Today panel open this one tab.

Tapping the companion's picture counts toward its chibi, if it has one and the server lists it
as unlocked: a hint from the fourth tap, and on the last the picture turns chibi and the server
is told. The art has no marked face area, so the whole picture counts."""

import enum
import time

from aqt.qt import (
    QButtonGroup, QDialog, QEasingCurve, QHBoxLayout, QLabel, QPushButton, QVariantAnimation, QVBoxLayout, QWidget, Qt,
)

from . import companion_art, companion_unlock, inbox, moods, share_ui
from .companion_reveal import Motion
from .companion_unlock import Choice
from .language import tr

TODAY_PX = 128
TODAY_ART = "ankiquest_companion_today"

# The chibi grows in from this share of her size, overshooting a little, as a pop.
POP_FROM = 0.4
POP_MS = 350
# Room around the picture for the overshoot, so the tab does not move.
POP_ROOM = 1.15
FACE_PX = 64
POSE_PX = 44
CARD = "ankiquest_companion_card"



class _Window(enum.Enum):
    """The picker window's lifetime: closing it, or deleting it, ends its server work."""

    OPEN = "open"
    CLOSED = "closed"


# Every companion in the picker's order.
ORDER = (moods.AKI, moods.ANKILOPE_ID, moods.COW, moods.ANKI_TAN, moods.NONE)

# A selected card has the highlight colour's border.
_STYLE = (
    "QPushButton#%s{padding:8px;border:1px solid palette(mid);border-radius:10px}"
    "QPushButton#%s:checked{border:3px solid palette(highlight)}"
) % (CARD, CARD)


def _load(api):
    """The account's companion and the server's unlocks."""
    return api.companion(), companion_unlock.fetch(api)


def _locked_lines(progress):
    """The condition and progress a locked card shows, leaving out what this add-on cannot word."""
    found = (companion_unlock.condition(progress, tr), companion_unlock.reached(progress, tr))
    return [line for line in found if line]


def _label(text):
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _card(companion, progress=None):
    """A checkable card: the companion's preview poses with its name under them. A locked one,
    given its `progress`, shows the poses as silhouettes with its condition and progress and
    cannot be chosen."""
    card = QPushButton()
    card.setObjectName(CARD)
    card.setCheckable(True)
    card.setProperty("companion", companion)
    card.setStyleSheet(_STYLE)
    layout = QVBoxLayout(card)
    poses = QHBoxLayout()
    for index, pose in enumerate(moods.preview(companion)):
        image = QLabel()
        picture = companion_art.pixmap(companion_art.pose_path(pose), companion, FACE_PX if index == 0 else POSE_PX)
        image.setPixmap(companion_art.silhouette(picture) if progress is not None else picture)
        poses.addWidget(image, 0, Qt.AlignmentFlag.AlignBottom)
    if poses.count() == 0:
        poses.addWidget(QLabel("○"))
    layout.addLayout(poses)
    labels = [_label(moods.NAMES.get(companion) or tr("No companion"))]

    # A locked card says how to earn it.
    if progress is not None:
        labels += [_label(line) for line in _locked_lines(progress)]
        card.setEnabled(False)
        card.setProperty("locked", True)
    for label in labels:
        layout.addWidget(label)

    # The labels let clicks through to the card.
    for index in range(poses.count()):
        poses.itemAt(index).widget().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    for label in labels:
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    # A button does not size itself by the layout inside it.
    card.setMinimumSize(layout.sizeHint())
    return card


class _Art(QLabel):
    """The companion's picture; a click is a tap, passed to `on_tap`."""

    def __init__(self):
        super().__init__()
        self.on_tap = None

    def tap(self):
        if self.on_tap is not None:
            self.on_tap(self)

    def mousePressEvent(self, event):
        self.tap()
        super().mousePressEvent(event)


def _chibi_pose(pose, base, chibi):
    """The chibi's version of her base's `pose`; poses drawn for no one in particular stay."""
    prefix = base + "_"
    return chibi + "_" + pose[len(prefix):] if pose.startswith(prefix) else pose


def _today(companion, mood, streak):
    """The chosen companion large in today's pose, its name and a line saying why it feels so."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    pose = moods.mood_pose(companion, mood, streak)
    if pose is not None:
        art = _Art()
        art.setObjectName(TODAY_ART)
        art.setProperty("companion", companion)
        art.setProperty("pose", pose)
        art.setPixmap(companion_art.pixmap(companion_art.pose_path(pose), companion, TODAY_PX))
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setFixedSize(round(TODAY_PX * POP_ROOM), round(TODAY_PX * POP_ROOM))
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
    name = _label(moods.NAMES.get(companion) or tr("No companion"))
    name.setStyleSheet("font-weight:bold;font-size:15px")
    layout.addWidget(name)

    # No companion has no mood.
    if pose is not None:
        text, values = moods.mood_line(mood, streak)
        line = _label(tr(text) % values)
        line.setWordWrap(True)
        layout.addWidget(line)
    return box


class Picker:
    """The companion tab for `api`'s account, `today` being the streak mood and streak
    (moods.today_mood). `client()` answers the signed-in client; the tab's server work runs only
    while its window is open and that is still `api`'s account and the profile it opened for. `on_saved(companion)` runs
    after a save. `motion` says whether a found chibi pops in; `clock` answers milliseconds for
    counting taps."""

    def __init__(self, parent, mw, api, client, current, on_saved, today=(moods.MOOD_UNKNOWN, 0), motion=Motion.FULL, clock=None):
        self._mw, self._api, self._client, self._on_saved = mw, api, client, on_saved
        self._profile = mw.pm.profile
        self._loaded = current
        # None until the server answers; until then only the current companion is offered.
        self._found = None
        self._cards = {}

        # Nothing counts toward a chibi until the server lists what is unlocked.
        self._egg = companion_unlock.Egg(())
        self._motion = motion
        self._clock = clock or (lambda: time.monotonic_ns() // 1_000_000)
        self._pop = None

        dialog = self.dialog = QDialog(parent)

        # Closing or deleting the window cancels queued work and drops replies, which would
        # otherwise reach deleted widgets.
        self._window = _Window.OPEN
        dialog.finished.connect(self._close)
        dialog.destroyed.connect(self._close)
        dialog.setWindowTitle(tr("Study companion"))
        dialog.setWindowIcon(companion_art.icon(current or moods.AKI))
        layout = QVBoxLayout(dialog)
        self.today = _today(current or moods.AKI, *today)
        layout.addWidget(self.today)
        art = self.today.findChild(QLabel, TODAY_ART)
        if art is not None:
            art.on_tap = self._tapped
        self._hint = QLabel()
        self._hint.setObjectName("ankiquest_companion_hint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._hint.setTextFormat(Qt.TextFormat.PlainText)
        self._hint.hide()
        self.today.layout().addWidget(self._hint)
        layout.addWidget(QLabel(tr("Choose who cheers you on.")))
        self._row = QHBoxLayout()
        layout.addLayout(self._row)
        self._group = QButtonGroup(dialog)
        self._group.setExclusive(True)
        self._status = QLabel(tr("Loading…"))
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(dialog.reject)
        self._save_button = QPushButton(tr("Save"))
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)

        self._show_cards(current)
        self._run(lambda: _load(api), self._arrived)

    def _close(self, *_):
        self._window = _Window.CLOSED

    def _owns(self):
        """Whether the tab is open and `api`'s account is still signed in on the profile the tab
        opened for."""
        if self._window == _Window.CLOSED:
            return False
        return self._profile is self._mw.pm.profile and share_ui.same_account(self._api, self._client())

    def _run(self, work, done):
        """Runs `work` in the background for this tab's window, account and profile; closing the
        tab, a sign-out or a profile change cancels it, even once queued, and drops its reply."""
        share_ui.run_owned(self._mw.taskman.run_in_background, self._owns, work, done)

    def _show_cards(self, selected):
        """One card per companion the picker offers, in its order, `selected` checked."""
        for card in self._cards.values():
            self._group.removeButton(card)
            self._row.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = {}
        for companion in ORDER:
            offered = companion_unlock.choice(companion, self._found, selected)
            if offered == Choice.HIDDEN:
                continue
            progress = self._found.progress[companion] if offered == Choice.LOCKED else None
            card = _card(companion, progress)
            self._group.addButton(card)
            self._row.addWidget(card)
            self._cards[companion] = card
        if selected in self._cards:
            self._cards[selected].setChecked(True)

    def _arrived(self, future):
        try:
            companion, found = future.result()
        except RuntimeError:
            return
        except Exception as error:
            print("ankiquest companion:", error)
            self._status.setText(inbox.failure("Could not load your study companion (%s).", error))
            return
        self._status.hide()
        self._loaded, self._found = companion, found
        self._egg = companion_unlock.Egg(found.unlocks)
        self._show_cards(companion)

    def _tapped(self, art):
        """Counts a tap on the companion's picture: shows the hint, or on the last tap turns it
        chibi and asks the server for her."""
        base = art.property("companion")
        tapped = self._egg.tap(base, self._clock(), tr)
        self._hint.setText(tapped.hint or "")
        self._hint.setVisible(tapped.hint is not None)
        if tapped.chibi is None:
            return
        self._become(art, base, tapped.chibi)
        self._run(lambda: self._api.unlock(tapped.chibi), self._unlocked)

    def _become(self, art, base, chibi):
        """Swaps the picture for the chibi's, popping in unless motion is reduced."""
        pose = _chibi_pose(art.property("pose"), base, chibi)
        picture = companion_art.pixmap(companion_art.pose_path(pose), chibi, TODAY_PX)
        art.setProperty("companion", chibi)
        art.setProperty("pose", pose)
        if self._motion == Motion.REDUCED:
            art.setPixmap(picture)
            return

        # A short grow with an overshoot.
        def grow(scale):
            size = max(1, round(TODAY_PX * scale))
            art.setPixmap(picture.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        pop = self._pop = QVariantAnimation(art)
        pop.setStartValue(POP_FROM)
        pop.setEndValue(1.0)
        pop.setDuration(POP_MS)
        pop.setEasingCurve(QEasingCurve.Type.OutBack)
        pop.valueChanged.connect(grow)
        grow(POP_FROM)
        pop.start()

    def _unlocked(self, future):
        try:
            future.result()
        except RuntimeError:
            return
        except Exception as error:
            print("ankiquest companion:", error)
            self._status.setText(tr("Could not save your study companion (%s).") % error)
            self._status.show()

    def chosen(self):
        card = self._group.checkedButton()
        return card.property("companion") if card is not None else None

    def _save(self):
        chosen = self.chosen()
        if chosen is None or chosen == self._loaded:
            self.dialog.accept()
            return

        # A tab left open across a sign-out or profile change saves nothing.
        if not self._owns():
            self.dialog.reject()
            return
        self._save_button.setEnabled(False)
        self._run(lambda: self._api.set_companion(chosen), lambda future: self._saved(future, chosen))

    def _saved(self, future, chosen):
        try:
            future.result()
        except RuntimeError:
            return
        except Exception as error:
            self._save_button.setEnabled(True)
            self._status.setText(tr("Could not save your study companion (%s).") % error)
            self._status.show()
            return
        self._loaded = chosen
        self._on_saved(chosen)
        self.dialog.accept()


def open_picker(parent, mw, api, client, current, on_saved, today=(moods.MOOD_UNKNOWN, 0), motion=Motion.FULL):
    """Shows the companion tab for `api`'s account and returns it; `client()` answers the
    signed-in client."""
    picker = Picker(parent, mw, api, client, current, on_saved, today, motion)
    picker.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    picker.dialog.show()
    return picker
