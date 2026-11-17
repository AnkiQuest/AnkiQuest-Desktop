"""One completed-deck prompt per Anki day, after the session's moments close."""

from enum import Enum, auto

from aqt.qt import QCheckBox, QDialog, QLineEdit, QPushButton, QVBoxLayout, QWidget, Qt

from . import deck_moments, deck_names, moment_share, share_ui
from .language import tr

_NAME_LIMIT = 120


class _Phase(Enum):
    CHECKING = auto()
    WAITING = auto()
    VISIBLE = auto()
    OPEN = auto()
    CLOSED = auto()


class _Prompt:
    def __init__(self, presenter, api, summary):
        self._presenter, self._addon, self._api = presenter, presenter._addon, api
        self._profile, self._col = self._addon.mw.pm.profile, self._addon.mw.col
        self._summary, self._record = summary, None
        self._key = (summary["day"], summary["deck"]["id"])
        self._phase = _Phase.CHECKING
        self._dialog = QDialog(self._addon.mw)
        self._dialog.setWindowTitle(tr("Deck complete"))
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog.finished.connect(self._finished)
        root = QVBoxLayout(self._dialog)
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
        root.addWidget(self._widget)
        quiet = QCheckBox(tr("Don't ask again"))
        quiet.toggled.connect(self._mute)
        root.addWidget(quiet)
        later = QPushButton(tr("Not now"))
        later.clicked.connect(self._dialog.reject)
        root.addWidget(later)
        self._dialog.setMinimumWidth(min(380, self._dialog.screen().availableGeometry().width()))

    def _owned(self):
        return (self._phase is not _Phase.CLOSED and self._presenter._completion is self
                and self._presenter._owns(self._api, self._profile) and self._addon.mw.col is self._col)

    def _run(self, work, done, **options):
        share_ui.run_owned(self._addon.mw.taskman.run_in_background, self._owned, work, done, **options)

    def _start(self):
        self._run(lambda: deck_moments._finished(self._col, self._summary["deck"], self._summary["finished_at"]),
                  self._verified, uses_collection=True)

    def _verified(self, future):
        try:
            self._record = future.result()
        except Exception:
            self._record = None
        if self._record is None:
            self._close()
            return
        api = self._api
        self._run(lambda: (api.capabilities(), api.deck_settings()), self._available)

    def _available(self, future):
        try:
            features, settings = future.result()
        except Exception:
            self._close()
            return
        reference = {"deck": {"id": self._record["id"], "name": "Deck"}}
        if (not moment_share._supported(reference, features) or deck_moments._automatic(settings, self._record)
                or not settings.get("recipients")):
            self._close()
            return
        self._phase = _Phase.WAITING
        self._name.setText(deck_names._choice(self._profile, self._api, self._record))
        self._widget.show()
        self._presenter._schedule()

    def _show(self):
        if self._phase is not _Phase.WAITING or not self._owned():
            return
        # Count only an actually displayed prompt, not a failed check or a closed profile.
        saved = deck_moments._prompts(self._profile, self._api)
        saved.setdefault("shown", {})[self._record["id"]] = self._summary["day"]
        self._phase = _Phase.VISIBLE
        self._changed(self._name.text())
        self._dialog.show()

    def _mute(self, checked):
        if self._owned():
            deck_moments._prompts(self._profile, self._api)["muted"] = checked

    def _showing(self):
        return self._phase in (_Phase.VISIBLE, _Phase.OPEN)

    def _finished(self, _result):
        self._phase = _Phase.CLOSED
        for child in self._dialog.findChildren(QDialog):
            child.close()
        self._presenter._schedule()

    def _close(self):
        if self._phase is _Phase.CLOSED:
            return
        self._phase = _Phase.CLOSED
        self._dialog.close()

    def _changed(self, text):
        # Qt's maxLength counts UTF-16 units; the shared name limit counts code points.
        if len(text) > _NAME_LIMIT:
            self._name.setText(text[:_NAME_LIMIT])
        self._share.setEnabled(self._phase is _Phase.VISIBLE and bool(text.strip()))

    def _open(self):
        if self._phase is not _Phase.VISIBLE or not self._owned():
            return
        name = " ".join(self._name.text().split())[:_NAME_LIMIT]
        if not name:
            return
        record = self._record

        def sent():
            # Cancel and failed requests leave the remembered name alone.
            if self._owned():
                deck_names._choose(self._profile, self._api, record, name)

        win = {"deck": {"id": self._record["id"], "name": name}, "kind": "deck",
               "title": tr("Deck complete"), "body": tr("I finished my %s studies for today.") % name}
        self._phase = _Phase.OPEN
        self._changed(name)
        window = share_ui.win_dialog(self._dialog, self._api, win,
                                     self._addon.current_companion(), self._addon.client, self._run, on_sent=sent)
        window.finished.connect(self._closed)
        window.show()

    def _closed(self, _result):
        if self._owned():
            self._phase = _Phase.VISIBLE
            self._changed(self._name.text())
