"""The study companion picker: a card per companion with a preview of its poses.

Companions earned at a milestone show as a greyed silhouette with their condition and progress
until the server has unlocked them (companion_unlock); secret ones stay hidden. Settings and
Tools > AnkiQuest > Study companion both open this one picker."""

from aqt.qt import QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, Qt

from . import companion_art, companion_unlock, moods
from .companion_unlock import Choice
from .language import tr

FACE_PX = 64
POSE_PX = 44
CARD = "ankiquest_companion_card"

# Every companion in the picker's order.
ORDER = (moods.AKI, moods.ANKILOPE_ID, moods.COW, moods.NONE)

# A selected card has the highlight colour's border.
_STYLE = (
    "QPushButton#%s{padding:8px;border:1px solid palette(mid);border-radius:10px}"
    "QPushButton#%s:checked{border:3px solid palette(highlight)}"
) % (CARD, CARD)


def _load(api):
    """The account's companion and the server's unlocks."""
    features = api.capabilities()
    return api.companion(), companion_unlock.fetch(api, features)


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
    card.setMinimumHeight(card.sizeHint().height())
    return card


class Picker:
    """The picker window for `api`'s account. `on_saved(companion)` runs after a save."""

    def __init__(self, parent, mw, api, current, on_saved):
        self._mw, self._api, self._on_saved = mw, api, on_saved
        self._loaded = current
        # None until the server answers; until then only the current companion is offered.
        self._found = None
        self._cards = {}

        dialog = self.dialog = QDialog(parent)
        dialog.setWindowTitle(tr("Study companion"))
        dialog.setWindowIcon(companion_art.icon(current or moods.AKI))
        layout = QVBoxLayout(dialog)
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
        mw.taskman.run_in_background(lambda: _load(api), self._arrived)

    def _show_cards(self, selected):
        """One card per companion the picker offers, in its order, `selected` checked."""
        for card in self._cards.values():
            self._group.removeButton(card)
            self._row.removeWidget(card)
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
            self._status.setText(tr("Could not load your study companion (%s).") % error)
            return
        self._status.hide()
        self._loaded, self._found = companion, found
        self._show_cards(companion)

    def chosen(self):
        card = self._group.checkedButton()
        return card.property("companion") if card is not None else None

    def _save(self):
        chosen = self.chosen()
        if chosen is None or chosen == self._loaded:
            self.dialog.accept()
            return
        self._save_button.setEnabled(False)
        self._mw.taskman.run_in_background(lambda: self._api.set_companion(chosen), lambda future: self._saved(future, chosen))

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


def open_picker(parent, mw, api, current, on_saved):
    """Shows the picker for `api`'s account and returns it."""
    picker = Picker(parent, mw, api, current, on_saved)
    picker.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    picker.dialog.show()
    return picker
