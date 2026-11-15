"""One native recipient picker for server wins, including companion unlocks."""

import time
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus

from aqt.qt import QCheckBox, QDialog, QLabel, QLineEdit, QPushButton, QScrollArea, QTimer, QVBoxLayout, QWidget, Qt

from . import moment_share as model, share, share_ui
from .inbox import error_text
from .language import tr

_UNDO_TICK = 1000
_PREVIEW_WIDTH = 240


class _Phase(Enum):
    LOADING = "loading"
    READY = "ready"
    SENDING = "sending"
    RETRACTING = "retracting"
    LEGACY = "legacy"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True)
class _Delivered:
    _sent: model._Sent


class _Picker:
    def __init__(self, parent, api, win, companion, current_client, run):
        self._api, self._win = api, win
        self._current = current_client
        self._phase, self._choice = _Phase.LOADING, model._Choice.NOBODY
        self._targets, self._rows = (), []
        host = self._host(parent)
        self._pm = getattr(host, "pm", None)
        taskman = getattr(host, "taskman", None)
        # This window keeps its win when the moment card behind it changes selection.
        self._background = taskman.run_in_background if taskman is not None else run
        self._profile = getattr(self._pm, "profile", None)
        self._recents = self._profile if self._profile is not None else {}
        self._dialog = QDialog(parent)
        self._dialog.setWindowTitle(tr("Share this win"))
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog.finished.connect(self._closed)
        self._dialog.destroyed.connect(self._destroyed)
        layout = QVBoxLayout(self._dialog)
        layout.addLayout(share_ui._head(win, companion))
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.hide()
        layout.addWidget(self._preview)
        self._form = QWidget()
        form = QVBoxLayout(self._form)
        form.setContentsMargins(0, 0, 0, 0)
        form.addWidget(share_ui._plain(tr("Send to")))
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Search friends and groups"))
        self._search.setAccessibleName(tr("Search friends and groups"))
        self._search.textChanged.connect(self._filter)
        form.addWidget(self._search)
        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        inner = QWidget()
        self._list = QVBoxLayout(inner)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._area.setWidget(inner)
        form.addWidget(self._area)
        self._empty = share_ui._plain(tr("Add friends in AnkiQuest to send them your moments."))
        form.addWidget(self._empty)
        self._invite = QPushButton(tr("Invite a friend"))
        self._invite.clicked.connect(self._copy_invite)
        form.addWidget(self._invite)
        form.addWidget(share_ui._plain(tr("Add a note (optional)")))
        self._note = QLineEdit()
        self._note.setAccessibleName(tr("Add a note (optional)"))
        self._note.textChanged.connect(self._note_changed)
        form.addWidget(self._note)
        self._send = QPushButton(tr("Send"))
        self._send.clicked.connect(self._submit)
        form.addWidget(self._send)
        layout.addWidget(self._form)
        self._form.hide()
        self._status = share_ui._plain(tr("Loading…"))
        layout.addWidget(self._status)
        self._undo = QPushButton(tr("Undo"))
        self._undo.clicked.connect(self._retract)
        self._undo.hide()
        layout.addWidget(self._undo)
        self._retry = QPushButton(tr("Retry"))
        self._retry.clicked.connect(self._load)
        self._retry.hide()
        layout.addWidget(self._retry)
        self._sharing = share_ui.Sharing(self._dialog, api, win, current_client, self._run, self._status, companion)
        self._exports = QWidget()
        exports = QVBoxLayout(self._exports)
        self._legacy, *options = share_ui._buttons(self._sharing)
        self._legacy.hide()
        layout.addWidget(self._legacy)
        for button in options:
            exports.addWidget(button)
        self._exports.hide()
        self._more = QPushButton(tr("More apps…"))
        self._more.setCheckable(True)
        self._more.toggled.connect(self._exports.setVisible)
        layout.addWidget(self._more)
        layout.addWidget(self._exports)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self._dialog.close)
        layout.addWidget(close)
        self._timer = QTimer(self._dialog)
        self._timer.timeout.connect(self._undo_state)
        self._timer.start(_UNDO_TICK)
        self._dialog.resize(520, 640)
        self._load()

    @staticmethod
    def _host(parent):
        while parent is not None:
            pm = getattr(parent, "pm", None)
            if pm is not None:
                return parent
            parent = parent.parentWidget()
        return None

    def _closed(self, _result):
        self._phase = _Phase.CLOSED
        self._timer.stop()

    def _destroyed(self):
        self._phase = _Phase.CLOSED

    def _owns(self):
        return (self._phase is not _Phase.CLOSED
                and getattr(self._pm, "profile", None) is self._profile
                and share_ui.same_account(self._api, self._current()))

    def _run(self, work, done):
        if not self._owns():
            return

        def guarded():
            # A queued request must not start after the account or profile changed.
            return work() if self._owns() else None

        def arrived(future):
            if self._owns():
                done(future)

        self._background(guarded, arrived)

    def _load(self):
        if not self._owns():
            return
        self._phase = _Phase.LOADING
        self._retry.hide()
        self._status.setText(tr("Loading…"))
        recent = model._recent(self._recents, self._api)
        self._run(lambda: model._load(self._api, self._win, recent), self._loaded)

    def _loaded(self, future):
        try:
            targets = future.result()
        except Exception as error:
            self._phase = _Phase.ERROR
            self._status.setText(tr("Couldn't load friends (%s).") % error_text(error))
            self._retry.show()
            return
        self._status.clear()
        if targets is None:
            self._phase = _Phase.LEGACY
            self._legacy.show()
            self._more.setChecked(True)
            return
        self._phase, self._targets = _Phase.READY, targets
        self._form.show()
        self._empty.setVisible(not targets)
        self._invite.setVisible(not targets)
        self._search.setVisible(bool(targets))
        self._area.setVisible(bool(targets))
        if targets:
            self._row(model._Choice.CIRCLE, tr("All friends"))
            for target in targets:
                self._row(target, target._label)
        self._refresh()
        if share.has_card(self._win):
            self._sharing.with_card(self._picture)

    def _row(self, target, label):
        check = QCheckBox(label)
        check.clicked.connect(lambda _checked, value=target: self._select(value))
        self._rows.append((target, check))
        self._list.addWidget(check)

    def _select(self, target):
        if self._phase is not _Phase.READY or not self._owns():
            return
        self._choice = model._toggle(self._choice, target)
        self._refresh()

    def _refresh(self):
        picked = self._choice._targets if isinstance(self._choice, model._Picked) else ()
        for target, check in self._rows:
            check.setChecked(target is self._choice or target in picked)
        self._send.setEnabled(self._phase is _Phase.READY and model._audience(self._choice) is not None)

    def _filter(self, text):
        text = text.strip().lower()
        for target, check in self._rows:
            key = "" if target is model._Choice.CIRCLE else str(target._id).lower()
            check.setVisible(target is model._Choice.CIRCLE or text in check.text().lower() or text in key)

    def _note_changed(self, text):
        if len(text) > model._MAX_NOTE:
            self._note.setText(text[:model._MAX_NOTE])

    def _picture(self, found):
        image = share_ui.picture(found["png"])
        if image is not None:
            from aqt.qt import QPixmap
            self._preview.setPixmap(QPixmap.fromImage(image).scaledToWidth(_PREVIEW_WIDTH, Qt.TransformationMode.SmoothTransformation))
            self._preview.show()
        if self._phase is _Phase.READY:
            self._status.clear()

    def _submit(self):
        if self._phase is not _Phase.READY or not self._owns() or model._audience(self._choice) is None:
            return
        self._phase = _Phase.SENDING
        self._form.setEnabled(False)
        self._status.setText(tr("Sharing…"))
        choice, note = self._choice, self._note.text()

        def sent(future):
            try:
                receipt = future.result()
            except Exception as error:
                self._phase = _Phase.READY
                self._form.setEnabled(True)
                self._status.setText(tr("Couldn't share it (%s).") % error_text(error))
                self._refresh()
                return
            model._remember(self._recents, self._api, choice)
            self._phase = _Delivered(receipt)
            self._status.setText(share.sent_text(receipt._recipients, tr))
            self._undo_state()

        self._run(lambda: model._send(self._api, self._win, choice, note), sent)

    def _undo_state(self):
        if not self._owns():
            self._undo.hide()
            return
        receipt = self._phase._sent if isinstance(self._phase, _Delivered) else None
        available = bool(receipt and receipt._recipients > 0 and isinstance(receipt._until, int)
                         and receipt._until > int(time.time() * 1000))
        self._undo.setVisible(available)
        self._undo.setEnabled(available)

    def _retract(self):
        self._undo_state()
        if not isinstance(self._phase, _Delivered) or not self._undo.isEnabled() or not self._owns():
            return
        delivered = self._phase
        self._phase = _Phase.RETRACTING
        self._undo.setEnabled(False)

        def retracted(future):
            try:
                future.result()
            except Exception as error:
                if getattr(error, "status", None) == HTTPStatus.CONFLICT:
                    self._phase = _Phase.READY
                    self._status.setText(tr("It is too late to undo this share."))
                    self._form.setEnabled(True)
                    self._refresh()
                else:
                    self._phase = delivered
                    self._status.setText(tr("Couldn't undo this share (%s).") % error_text(error))
            else:
                self._phase = _Phase.READY
                self._form.setEnabled(True)
                self._status.setText(tr("Share taken back where possible."))
                self._refresh()
            self._undo_state()

        self._run(lambda: model._retract(self._api, delivered._sent), retracted)

    def _copy_invite(self):
        if self._owns():
            self._status.setText(share_ui.copy_text(self._win, self._api.base))


def _dialog(parent, api, win, companion, current_client, run):
    picker = _Picker(parent, api, win, companion, current_client, run)
    picker._dialog._picker = picker
    return picker._dialog
