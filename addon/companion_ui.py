"""The study companion picker: a card per companion with a preview of its poses.

Tapping Ankilope's card in a row unlocks the hidden cow (companion_unlock); nothing hints at it.
Settings and Tools > AnkiQuest > Study companion both open this one picker."""

import time

from aqt.qt import QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, Qt

from . import companion_art, companion_unlock, moods
from .language import tr

FACE_PX = 64
POSE_PX = 44
CARD = "ankiquest_companion_card"

# A selected card has the highlight colour's border.
_STYLE = (
    "QPushButton#%s{padding:8px;border:1px solid palette(mid);border-radius:10px}"
    "QPushButton#%s:checked{border:3px solid palette(highlight)}"
) % (CARD, CARD)


def _now_ms():
    return int(time.time() * 1000)


def _load(api):
    """The account's companion, the server's features and its unlocks (None without them)."""
    features = api.capabilities()
    return api.companion(), features, companion_unlock.fetch(api, features)


def _save(api, chosen, pending):
    """Sends unlocks made here before the companion that needs them; answers the server's
    unlocks, or None when it has none."""
    server = companion_unlock.send(api, pending) if pending else None
    api.set_companion(chosen)
    return server


def _card(companion):
    """A checkable card: the companion's preview poses with its name under them."""
    card = QPushButton()
    card.setObjectName(CARD)
    card.setCheckable(True)
    card.setProperty("companion", companion)
    card.setStyleSheet(_STYLE)
    layout = QVBoxLayout(card)
    poses = QHBoxLayout()
    for index, pose in enumerate(moods.preview(companion)):
        image = QLabel()
        image.setPixmap(companion_art.pixmap(companion_art.pose_path(pose), companion, FACE_PX if index == 0 else POSE_PX))
        poses.addWidget(image, 0, Qt.AlignmentFlag.AlignBottom)
    if poses.count() == 0:
        poses.addWidget(QLabel("○"))
    layout.addLayout(poses)
    name = QLabel(moods.NAMES.get(companion) or tr("No companion"))
    name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    layout.addWidget(name)

    # The labels let clicks through to the card.
    for index in range(poses.count()):
        poses.itemAt(index).widget().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    card.setMinimumHeight(card.sizeHint().height())
    return card


class Picker:
    """The picker window for `api`'s account. `on_saved(companion)` runs after a save."""

    def __init__(self, parent, mw, api, current, on_saved):
        self._mw, self._api, self._on_saved = mw, api, on_saved
        self._prefs = mw.pm.profile
        self._key = companion_unlock.account(api)
        self._taps = companion_unlock.Taps()
        self._loaded = current
        # Unknown (None) until the server answers; offline the cow can still be found.
        self._features = None
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
        self._message = QLabel()
        self._message.setObjectName("ankiquest_companion_message")
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.hide()
        layout.addWidget(self._message)
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

    def _unlocked(self):
        return companion_unlock.unlocked(self._prefs, self._key)

    def _show_cards(self, selected):
        """One card per companion this player may choose, in the picker's order."""
        shown = [moods.AKI, moods.ANKILOPE_ID]
        if moods.COW in self._unlocked() or selected == moods.COW:
            shown.append(moods.COW)
        shown.append(moods.NONE)
        for companion in shown:
            if companion in self._cards:
                continue
            card = _card(companion)
            card.clicked.connect(lambda _checked=False, chosen=companion: self._tapped(chosen))
            self._group.addButton(card)
            self._row.insertWidget(shown.index(companion), card)
            self._cards[companion] = card
        if selected in self._cards:
            self._cards[selected].setChecked(True)

    def _arrived(self, future):
        try:
            companion, features, server = future.result()
        except RuntimeError:
            return
        except Exception as error:
            print("ankiquest companion:", error)
            self._status.setText(tr("Could not load your study companion (%s).") % error)
            return
        self._status.hide()
        self._loaded, self._features = companion, features
        if server is not None:
            companion_unlock.settle(self._prefs, self._key, server)
        self._show_cards(companion)

    def _tapped(self, chosen):
        if not self._taps.tap(chosen, _now_ms()) or moods.COW in self._cards:
            return
        # A server known to lack unlocks could not keep the cow.
        if self._features is not None and companion_unlock.FEATURE not in self._features:
            return
        companion_unlock.record(self._prefs, self._key, moods.COW)
        self._message.setText(tr("%s joined you!") % moods.NAMES[moods.COW])
        self._message.show()
        self._show_cards(moods.COW)
        self._mw.taskman.run_in_background(lambda: companion_unlock.send(self._api, [moods.COW]), self._sent)

    def _sent(self, future):
        # Offline, the unlock stays pending and the regular poll sends it.
        try:
            server = future.result()
        except Exception as error:
            print("ankiquest unlock:", error)
            return
        if server is not None:
            companion_unlock.settle(self._prefs, self._key, server)

    def chosen(self):
        card = self._group.checkedButton()
        return card.property("companion") if card is not None else None

    def _save(self):
        chosen = self.chosen()
        if chosen is None or chosen == self._loaded:
            self.dialog.accept()
            return
        pending = companion_unlock.pending(self._prefs, self._key) if chosen == moods.COW else []
        self._save_button.setEnabled(False)
        self._mw.taskman.run_in_background(lambda: _save(self._api, chosen, pending), lambda future: self._saved(future, chosen))

    def _saved(self, future, chosen):
        try:
            server = future.result()
        except RuntimeError:
            return
        except Exception as error:
            self._save_button.setEnabled(True)
            self._status.setText(tr("Could not save your study companion (%s).") % error)
            self._status.show()
            return
        if server is not None:
            companion_unlock.settle(self._prefs, self._key, server)
        self._loaded = chosen
        self._on_saved(chosen)
        self.dialog.accept()


def open_picker(parent, mw, api, current, on_saved):
    """Shows the picker for `api`'s account and returns it."""
    picker = Picker(parent, mw, api, current, on_saved)
    picker.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    picker.dialog.show()
    return picker
