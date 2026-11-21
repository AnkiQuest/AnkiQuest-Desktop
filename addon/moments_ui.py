"""Poll/upload/session -> profile queue -> one card on a resting screen."""

from copy import deepcopy
from enum import Enum, auto

from aqt.qt import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTimer, QVBoxLayout, QWidget, Qt

from . import companion_art, companion_reveal, conquests_ui, deck_moments_ui, inbox, moments, reveal_ui, share_ui, today
from .language import tr

_RESTING = ("overview", "deckBrowser", "congrats")


class _Phase(Enum):
    READY = auto()
    # A companion's unlock reveal is on screen; the card waits for it.
    REVEALING = auto()
    SHOWING = auto()
    DISMISSED = auto()
    # Aki's greeting is in front; cards wait until it closes.
    WAITING = auto()


class _Permission(Enum):
    UNKNOWN = auto()
    ENABLED = auto()
    DISABLED = auto()


class _Origin(Enum):
    AUTOMATIC = auto()
    PLAYER = auto()


class _Presenter:
    def __init__(self, addon):
        self._addon = addon
        self._owner = None
        self._profile = None
        self._card = None
        self._reveal = None
        self._completion = None
        self._phase = _Phase.READY
        self._permission = _Permission.UNKNOWN
        self._origin = _Origin.AUTOMATIC
        self._request = None
        self._summary = None

    def _sync_owner(self):
        api = self._addon.client()
        owner = (api.base, api.user, api.token)
        profile = self._addon.mw.pm.profile
        if owner != self._owner or profile is not self._profile:
            self._clear()
            self._owner, self._profile = owner, profile
        return api

    def _clear(self):
        card, self._card = self._card, None
        self._close_completion()
        self._close_reveal()
        self._owner = self._profile = self._request = self._summary = None
        self._phase, self._permission = _Phase.READY, _Permission.UNKNOWN
        self._origin = _Origin.AUTOMATIC
        if card is not None:
            card._dialog.close()

    def _owns(self, api, profile):
        current = self._addon.client()
        return profile is self._addon.mw.pm.profile and (api.base, api.user, api.token) == (current.base, current.user, current.token)

    def _offer(self, api, items, summary=None):
        if not items and summary is None:
            return
        profile = self._addon.mw.pm.profile
        if profile is None or not self._owns(api, profile):
            return
        self._sync_owner()
        moments._offer(profile, self._owner[:2], items)
        if summary is not None:
            self._summary = summary
            self._offer_completion(api, summary)
        if any(not item.get("local") for item in items):
            self._refresh_permission()
        self._schedule()

    def _offer_completion(self, api, summary):
        if not deck_moments_ui.deck_moments._prompt_due(self._profile, api, summary):
            return
        key = (summary["day"], summary["deck"]["id"])
        if self._completion is not None and self._completion._key == key:
            return
        self._close_completion()
        self._completion = deck_moments_ui._Prompt(self, api, summary)
        self._completion._start()

    def _close_completion(self):
        prompt, self._completion = self._completion, None
        if prompt is not None:
            prompt._close()

    def _refresh_permission(self):
        api = self._sync_owner()
        if self._request is not None or not api.configured:
            return
        request = self._request = object()
        self._permission = _Permission.UNKNOWN
        profile = self._profile

        def arrived(future):
            if self._request is not request or not self._owns(api, profile):
                return
            self._request = None
            try:
                self._permission = _Permission.DISABLED if future.result().get("celebrations") is False else _Permission.ENABLED
            except Exception as error:
                print("ankiquest moments:", error)
                return
            self._schedule()

        self._addon.mw.taskman.run_in_background(api.deck_settings, arrived)

    def _schedule(self):
        QTimer.singleShot(0, self._show)

    def _hold(self):
        """Keeps cards back while Aki's greeting is open."""
        self._sync_owner()
        self._phase = _Phase.WAITING

    def _release(self):
        if self._phase is not _Phase.WAITING:
            return
        self._phase = _Phase.READY
        self._schedule()

    def _transition(self, new_state, old_state):
        self._sync_owner()
        if new_state == "review":
            # Starting another review defers an open card; a pause never closes it.
            card, self._card = self._card, None
            self._close_completion()
            self._close_reveal()
            self._phase, self._origin = _Phase.READY, _Origin.AUTOMATIC
            self._summary = None
            if card is not None:
                card._dialog.close()
            return
        if new_state in _RESTING:
            if self._profile is not None and moments._pending(self._profile, self._owner[:2]):
                self._refresh_permission()
            self._schedule()

    def _open(self):
        self._sync_owner()
        self._origin, self._phase = _Origin.PLAYER, _Phase.READY
        if self._profile is not None:
            quiet = moments._quiet_count(self._profile, self._owner[:2])
            moments._clear_quiet(self._profile, self._owner[:2])
            if quiet and not moments._pending(self._profile, self._owner[:2]):
                self._addon.open_inbox()
            self._addon.redraw()
        self._show()

    def _count(self):
        api = self._sync_owner()
        if not api.configured or self._profile is None:
            return 0
        return len(moments._pending(self._profile, self._owner[:2])) + moments._quiet_count(self._profile, self._owner[:2])

    def _show(self):
        api = self._sync_owner()
        if (not api.configured or self._profile is None or self._addon.mw.state not in _RESTING
                or self._phase is _Phase.WAITING):
            return
        if self._completion is not None and self._completion._showing():
            return
        items = [item for item in moments._pending(self._profile, self._owner[:2]) if self._allowed(item)]
        # A greeting can open and close over a reveal, so the open window decides, not the phase.
        if self._reveal is not None:
            return
        # The independent completion prompt follows the last session card.
        if not items or self._phase is _Phase.DISMISSED:
            if self._card is None and self._completion is not None:
                self._completion._show()
            return
        if self._card is not None:
            self._card._append(items, self._summary)
            return

        # A companion that joined is revealed first; the card shows the rest afterwards.
        joined = next((item for item in items if companion_reveal.due(item)), None)
        if joined is not None:
            self._play(api, joined)
            return
        card = self._card = _Card(self._addon, api, self._profile, items, self._summary)
        self._phase = _Phase.SHOWING

        def finished(_result):
            if self._card is not card:
                return
            self._card = None
            if self._owns(api, card._profile) and self._addon.mw.state in _RESTING:
                moments._acknowledge(card._profile, (api.base, api.user), [item["key"] for item in card._items])
                self._phase = _Phase.DISMISSED
                self._addon.redraw()
                self._schedule()

        card._dialog.finished.connect(finished)
        card._dialog.show()

    def _play(self, api, item):
        """Plays the reveal for `item`. Closing it consumes the moment and marks its row read,
        so other devices show the moment card instead."""
        mw = self._addon.mw

        def sharing(dialog, run, status):
            if not item.get("share"):
                return None
            return share_ui.Sharing(dialog, api, item["share"], self._addon.client, run, status, moments.joined(item))

        # Choose, Share and marking the row read act for the account and profile the reveal
        # opened for; a sign-out or profile change cancels them, even once queued.
        profile = self._profile

        def owns():
            return self._owns(api, profile)

        def run(work, done):
            share_ui.run_owned(mw.taskman.run_in_background, owns, work, done)

        def choose(companion):
            if owns():
                self._addon.choose_companion(api, companion, run)

        window = self._reveal = reveal_ui.play(
            mw, item, reveal_ui.motion(self._addon.config()), self._addon.current_companion(), choose, sharing, run,
        )
        self._phase = _Phase.REVEALING

        def finished(_result):
            if self._reveal is not window:
                return
            self._reveal = None
            if self._phase is _Phase.REVEALING:
                self._phase = _Phase.READY
            if not owns():
                return
            moments._acknowledge(profile, (api.base, api.user), [item["key"]])
            run(lambda: inbox.mark_read(api, [item["notice"]]), _marked)
            self._addon.redraw()
            self._schedule()

        window.dialog.finished.connect(finished)

    def _close_reveal(self):
        """Closes a reveal without consuming its moment, so it plays again later."""
        window, self._reveal = self._reveal, None
        if window is None:
            return
        if self._phase is _Phase.REVEALING:
            self._phase = _Phase.READY
        window.dialog.close()

    def _allowed(self, item):
        if self._origin is _Origin.PLAYER:
            return True
        if (item["topic"] == "secured" or item.get("local") and item["topic"] == "goal") and not self._addon.config().get("goal_celebrations", True):
            return False
        return item.get("local") or self._permission is _Permission.ENABLED


def _marked(future):
    try:
        future.result()
    except Exception as error:
        print("ankiquest moments:", error)


class _Card:
    def __init__(self, addon, api, profile, items, summary):
        self._addon, self._api, self._profile = addon, api, profile
        self._items, self._summary = [], summary
        self._closed = False
        self._rendered = None
        self._dialog = QDialog(addon.mw)
        self._dialog.setWindowTitle(tr("Your moments"))
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog.finished.connect(lambda _result: setattr(self, "_closed", True))
        root = QVBoxLayout(self._dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._art = QLabel()
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._art)
        self._title = share_ui._plain("", True)
        self._body, self._date = share_ui._plain(""), share_ui._plain("")
        for widget in (self._title, self._body, self._date):
            layout.addWidget(widget)
        self._more = QPushButton()
        self._more.setCheckable(True)
        self._choices = QComboBox()
        self._choices.hide()
        self._more.toggled.connect(self._choices.setVisible)
        self._choices.currentIndexChanged.connect(self._render)
        layout.addWidget(self._more)
        layout.addWidget(self._choices)
        self._session = share_ui._plain("")
        layout.addWidget(self._session)
        self._day = share_ui._plain("")
        layout.addWidget(self._day)
        self._status = share_ui._plain("")
        layout.addWidget(self._status)
        self._actions = QVBoxLayout()
        layout.addLayout(self._actions)
        self._quiet = QCheckBox(tr("Don’t show session recaps again"))
        self._quiet.setChecked(not addon.config().get("session_summary", True))
        layout.addWidget(self._quiet)
        self._quiet.toggled.connect(self._recaps)
        row = QHBoxLayout()
        progress = QPushButton(tr("View progress"))
        progress.clicked.connect(addon.home.open_progress)
        row.addWidget(progress)
        row.addStretch(1)
        close = QPushButton(tr("Done"))
        close.clicked.connect(self._dialog.accept)
        row.addWidget(close)
        self._continue = QPushButton(tr("Continue studying"))
        self._continue.clicked.connect(self._resume)
        row.addWidget(self._continue)
        root.addLayout(row)
        bounds = self._dialog.screen().availableGeometry()
        self._dialog.setMinimumWidth(min(440, bounds.width()))
        self._dialog.resize(min(520, bounds.width()), min(640, bounds.height()))
        self._append(items, summary)

    def _resume(self):
        self._dialog.accept()
        self._addon.home.continue_studying()

    def _recaps(self, checked):
        self._addon.save_config({"session_summary": not checked})

    def _owned(self):
        return not self._closed and self._profile is self._addon.mw.pm.profile and share_ui.same_account(self._api, self._addon.client())

    def _run(self, work, done, uses_collection=False):
        rendered = self._rendered

        def current():
            return self._owned() and self._rendered is rendered

        share_ui.run_owned(self._addon.mw.taskman.run_in_background, current, work, done, uses_collection=uses_collection)

    def _append(self, items, summary):
        selected = self._choices.currentData()
        previous = next((item for item in self._items if item["key"] == selected), None)
        # A newly queued win must not erase an unsaved label in the current one.
        preserve = previous is not None and previous == next((item for item in items if item["key"] == selected), None)
        self._items = deepcopy(items)
        saved = [item["summary"] for item in items if item.get("summary")]
        self._summary = summary or max(saved, key=lambda value: value.get("finished_at", 0), default=None)
        # A recap is the fallback when all queued wins are disabled; otherwise it is the footer.
        choices = [item for item in items if item["topic"] != "session"] or items
        self._choices.blockSignals(True)
        self._choices.clear()
        for item in choices:
            self._choices.addItem(item["title"], item["key"])
        self._choices.setCurrentIndex(max(0, self._choices.findData(selected)))
        self._choices.blockSignals(False)
        self._more.setText(tr("and %d more") % (len(choices) - 1))
        self._more.setVisible(len(choices) > 1)
        self._choices.setVisible(len(choices) > 1 and self._more.isChecked())
        if preserve and self._choices.currentData() == selected:
            self._session_fields()
        else:
            self._render()

    def _session_fields(self):
        key = self._choices.currentData()
        self._session.setText(today.session_body(self._summary, tr) if self._summary else "")
        self._session.setVisible(self._summary is not None and not key.startswith("session:"))
        self._quiet.setVisible(self._summary is not None)
        self._continue.setVisible(bool(self._summary and self._summary.get("remaining", 0) > 0))
        self._day.setVisible(self._summary is not None)
        if self._summary:
            day = self._addon.home._session_day(self._summary)
            self._day.setText(day["label"])
            colours = {
                **{state: "background:#dff1c9;color:#254a12;" for state in ("met", "unverified")},
                "short": "background:#e9d8a6;color:#534619;",
                **{state: "background:#def0ff;color:#16527b;" for state in ("syncing", "protected", "frozen", "skipped")},
            }
            self._day.setStyleSheet("padding:6px;border-radius:6px;" + colours.get(day["state"], ""))

    def _render(self, _index=None):
        key = self._choices.currentData()
        item = next((item for item in self._items if item["key"] == key), None)
        if item is None:
            return
        self._rendered = object()
        title = self._addon.home._streak_title(item["summary"]) if item["topic"] == "secured" and item.get("local") and item.get("summary") else item["title"]
        self._title.setText(title)
        self._body.setText(item["body"])
        self._date.setText(inbox.when(item["at"] // 1000))
        self._status.clear()
        companion = moments.shown_companion(item, self._addon.current_companion())
        pose = moments._pose(item, companion)
        self._art.setVisible(pose is not None)
        if pose is not None:
            self._art.setPixmap(companion_art.pixmap(companion_art.pose_path(pose), companion, 112))
        self._session_fields()
        while self._actions.count():
            self._actions.takeAt(0).widget().deleteLater()
        if item["key"].startswith("conquered:"):
            try:
                at = int(item["key"].split(":", 1)[1])
            except ValueError:
                return
            self._conquest = conquests_ui._Conquest(self, at)
            self._actions.addWidget(self._conquest._widget)
            self._conquest._load()
            return
        win = item.get("share")
        if not win:
            return
        win = dict(win, picture_pose=pose)
        if item["topic"] == "secured" and item.get("streak"):
            win["picture_streak"] = item["streak"]
        sharing = share_ui.Sharing(self._dialog, self._api, win, self._addon.client, self._run, self._status, companion)
        friends, *options = share_ui._buttons(sharing)
        friends.setText(tr("Tell friends"))
        toggle, choices = share_ui.share_toggle(sharing, options)
        bar = QWidget()
        buttons = QHBoxLayout(bar)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(friends)
        buttons.addWidget(toggle)
        self._actions.addWidget(bar)
        self._actions.addWidget(choices)
