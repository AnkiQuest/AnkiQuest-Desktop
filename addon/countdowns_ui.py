"""The countdown list: add, edit and delete the player's events and exams."""

from aqt.qt import (
    QComboBox,
    QDate,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    Qt,
)
from . import countdowns
from .language import tr


def _tell(parent, text):
    from aqt.utils import showInfo
    showInfo(text, parent=parent)


def _qdate(day):
    return QDate(day.year, day.month, day.day)


def _event_dialog(parent, title, event, deck_names, first_day):
    """One event's form. Returns the edited event, or None when cancelled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)

    # Name, date and an optional deck, in the fixture's order.
    name = QLineEdit(event.name if event else "")
    name.setMaxLength(countdowns.MAX_NAME_CHARS)
    when = QDateEdit()
    when.setCalendarPopup(True)
    when.setDisplayFormat("yyyy-MM-dd")
    when.setDate(_qdate(countdowns.parse_date(event.date) if event else first_day))
    deck = QComboBox()
    deck.addItem(tr("No deck"), None)
    for found in filter(countdowns.usable_deck, deck_names):
        deck.addItem(found, found)
    if event and event.deck:
        if deck.findData(event.deck) < 0:
            deck.addItem(event.deck, event.deck)
        deck.setCurrentIndex(deck.findData(event.deck))
    for label, widget in ((tr("Name"), name), (tr("Date"), when), (tr("Deck (optional)"), deck)):
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)

    # Save refuses a blank name, so the list stays one the server stores.
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton(tr("Cancel"))
    cancel.clicked.connect(dialog.reject)
    save = QPushButton(tr("Save"))
    save.setDefault(True)

    def accept():
        if not name.text().strip():
            _tell(dialog, tr("Enter a name."))
            return
        dialog.accept()

    save.clicked.connect(accept)
    buttons.addWidget(cancel)
    buttons.addWidget(save)
    layout.addLayout(buttons)

    if not dialog.exec():
        return None
    return countdowns.Event(name.text().strip(), when.date().toString("yyyy-MM-dd"), deck.currentData())


class CountdownsDialog(QDialog):
    """The list in date order. Every change is saved at once through `save(list)`."""

    def __init__(self, parent, items, deck_names, today, save):
        super().__init__(parent)
        self.setWindowTitle(tr("Countdowns"))
        self._items = list(items)
        self._deck_names = deck_names
        self._today = today
        self._save = save
        layout = QVBoxLayout(self)

        note = QLabel(tr("Only you see your countdowns."))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._empty = QLabel(tr("Add an exam or event to count down to it."))
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        self._list = QListWidget()
        self._list.setObjectName("ankiquest_countdowns")
        self._list.itemDoubleClicked.connect(lambda _: self._edit())
        layout.addWidget(self._list)

        row = QHBoxLayout()
        self._add = QPushButton(tr("Add countdown"))
        self._add.clicked.connect(self._new)
        self._change = QPushButton(tr("Edit countdown"))
        self._change.clicked.connect(self._edit)
        self._delete = QPushButton(tr("Delete"))
        self._delete.clicked.connect(self._remove)
        for button in (self._add, self._change, self._delete):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self._list.currentRowChanged.connect(lambda _: self._buttons())
        self._show()

    def _show(self):
        # Rows keep the index of their event in the stored list.
        self._list.clear()
        order = sorted(range(len(self._items)), key=lambda index: self._items[index].date)
        for index in order:
            event = self._items[index]
            found = countdowns.days(self._today, countdowns.parse_date(event.date))
            text = "%s · %s" % (event.date, countdowns.headline(event, found, tr))
            if event.deck:
                text += " · " + event.deck
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(item)
        self._empty.setVisible(not self._items)
        self._buttons()

    def _buttons(self):
        chosen = self._list.currentItem() is not None
        self._change.setEnabled(chosen)
        self._delete.setEnabled(chosen)

    def _chosen(self):
        item = self._list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _store(self, items):
        """Saves `items` and shows them, unless the server would refuse the list: saving an
        unusable list would replace the player's events with an empty one."""
        value = countdowns.stored(items)
        if not countdowns.valid(value):
            _tell(self, tr("This countdown can't be saved. Choose another deck."))
            return
        self._items = items
        self._save(value)
        self._show()

    def _new(self):
        if len(self._items) >= countdowns.MAX_EVENTS:
            _tell(self, tr("You have the most countdowns you can keep. Delete one to add another."))
            return
        event = _event_dialog(self, tr("Add countdown"), None, self._deck_names, countdowns.first_date(self._today))
        if event is not None:
            self._store(self._items + [event])

    def _edit(self):
        index = self._chosen()
        if index is None:
            return
        event = _event_dialog(self, tr("Edit countdown"), self._items[index], self._deck_names, self._today)
        if event is not None:
            self._store(self._items[:index] + [event] + self._items[index + 1:])

    def _remove(self):
        index = self._chosen()
        if index is None:
            return
        self._store(self._items[:index] + self._items[index + 1:])
