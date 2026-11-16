"""A completed-deck action inside the session recap, using the common recipient picker."""

from enum import Enum, auto

from aqt.qt import QLineEdit, QPushButton, QVBoxLayout, QWidget

from . import deck_moments, deck_names, moment_share, share_ui
from .language import tr

_NAME_LIMIT = 120


class _Phase(Enum):
    HIDDEN = auto()
    CHECKING = auto()
    READY = auto()
    OPEN = auto()


class _Action:
    def __init__(self, card):
        self._card, self._key, self._record = card, None, None
        self._phase = _Phase.HIDDEN
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(share_ui._plain(tr("Deck complete"), True))
        layout.addWidget(share_ui._plain(tr("Deck name")))
        self._name = QLineEdit()
        self._name.setAccessibleName(tr("Deck name"))
        self._name.textChanged.connect(self._changed)
        layout.addWidget(self._name)
        self._share = QPushButton(tr("Share completed deck"))
        self._share.clicked.connect(self._open)
        layout.addWidget(self._share)
        self._widget.hide()

    def _owns(self, key, col):
        return (self._phase is not _Phase.HIDDEN and self._card._owned() and self._key == key
                and self._card._addon.mw.col is col and self._card._addon.config().get("session_summary", True))

    def _run(self, work, done, **options):
        key, col = self._key, self._card._addon.mw.col
        share_ui.run_owned(self._card._addon.mw.taskman.run_in_background,
                           lambda: self._owns(key, col), work, done, **options)

    def _update(self, summary):
        record = (summary or {}).get("deck")
        if not self._card._addon.config().get("session_summary", True):
            record = None
        key = (summary.get("finished_at"), record.get("id")) if record else None
        if key == self._key:
            return
        self._key, self._record, self._phase = key, None, _Phase.HIDDEN
        self._widget.hide()
        if not record:
            return
        self._phase = _Phase.CHECKING
        col = self._card._addon.mw.col
        self._run(lambda: deck_moments._finished(col, record, summary["finished_at"]), self._verified, uses_collection=True)

    def _verified(self, future):
        try:
            self._record = future.result()
        except Exception:
            self._record = None
        if self._record is None:
            self._phase = _Phase.HIDDEN
            return
        api = self._card._api
        self._run(lambda: (api.capabilities(), api.deck_settings()), self._available)

    def _available(self, future):
        try:
            features, settings = future.result()
        except Exception:
            self._phase = _Phase.HIDDEN
            return
        reference = {"deck": {"id": self._record["id"], "name": "Deck"}}
        if (not moment_share._supported(reference, features) or deck_moments._automatic(settings, self._record)
                or not settings.get("recipients")):
            self._phase = _Phase.HIDDEN
            return
        self._phase = _Phase.READY
        self._name.setText(deck_names._choice(self._card._profile, self._card._api, self._record))
        self._widget.show()
        self._changed(self._name.text())

    def _changed(self, text):
        if len(text) > _NAME_LIMIT:
            self._name.setText(text[:_NAME_LIMIT])
        self._share.setEnabled(self._phase is _Phase.READY and bool(text.strip()))

    def _open(self):
        if self._phase is not _Phase.READY or not self._card._owned():
            return
        name = " ".join(self._name.text().split())[:_NAME_LIMIT]
        if not name:
            return
        deck_names._choose(self._card._profile, self._card._api, self._record, name)
        win = {"deck": {"id": self._record["id"], "name": name}, "kind": "deck",
               "title": tr("Deck complete"), "body": tr("I finished my %s studies for today.") % name}
        self._phase = _Phase.OPEN
        self._changed(name)
        window = share_ui.win_dialog(self._card._dialog, self._card._api, win,
                                     self._card._addon.current_companion(), self._card._addon.client, self._run)
        window.finished.connect(self._closed)
        window.show()

    def _closed(self, _result):
        if self._card._owned():
            self._phase = _Phase.READY
            self._changed(self._name.text())
