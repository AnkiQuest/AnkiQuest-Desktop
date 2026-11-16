"""Exercise the real Qt window, event loop and delayed account-scoped replies."""

from concurrent.futures import Future
from copy import deepcopy
from os import environ
from types import SimpleNamespace
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from aqt.qt import QApplication, QDialog, QFont, QFontDatabase, QPushButton, QScrollArea, QWidget
from anki.collection import Collection

from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
ui = load_in_package("moments_qt", "moments_ui")
ui.tr = ui.conquests_ui.tr = ui.share_ui.tr = lambda text: text


class Moments(unittest.TestCase):
    def setUp(self):
        self.found = {"conquest": {"at": 50, "since": 0, "lapses": 5, "answers": 20},
                      "label": None, "told": False, "friends": 2, "win": 7}
        self.requests, self.tasks = [], []
        self.defer = False
        self.api = SimpleNamespace(configured=True, base="https://quest.test", user="sam", token="token",
                                   deck_settings=lambda: {"celebrations": True}, _request=self.request)
        self.mw = QWidget()
        self.mw.state = "review"
        self.mw.pm = SimpleNamespace(profile={})
        note = SimpleNamespace(fields=["B1L02", "Hund"], note_type=lambda: {"type": 0})
        card = SimpleNamespace(question=lambda: "<b>der Hund</b>", note=lambda: note, did=5, odid=0)
        self.mw.col = SimpleNamespace(db=SimpleNamespace(scalar=lambda *args: 1), get_card=lambda cid: card,
                                      decks=SimpleNamespace(name=lambda did: "German"))
        self.mw.taskman = SimpleNamespace(run_in_background=self.run_task)
        self.addon = SimpleNamespace(mw=self.mw, client=lambda: self.api, current_companion=lambda: "aki",
                                     config=lambda: {},
                                     save_config=Mock(), redraw=Mock(), open_inbox=Mock(),
                                     home=SimpleNamespace(open_progress=Mock(), continue_studying=Mock(),
                                         _streak_title=Mock(return_value="Streak minimum reached — syncing"),
                                         _session_day=Mock(return_value={"state": "frozen", "label": "Frozen — streak kept"})))
        self.presenter = ui._Presenter(self.addon)

    def tearDown(self):
        self.presenter._clear()
        self.mw.close()
        app.processEvents()

    def request(self, path, body=None, method=None):
        self.requests.append((path, body, method))
        if path.endswith("/label"):
            self.found["label"] = body["label"] if body else None
            return None
        if path.endswith("/tell"):
            self.found["told"] = method != "DELETE"
            self.found["undo_until"] = int(time.time() * 1000) + 10000
            return {"told": 2, "retracted": 2}
        return deepcopy(self.found)

    def run_task(self, work, done, uses_collection=False):
        if self.defer:
            self.tasks.append((work, done))
        else:
            self.complete((work, done))

    def complete(self, task):
        work, done = task
        future = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        done(future)

    def flush(self):
        for _ in range(3):
            app.processEvents()

    def item(self, key="level:4", topic="level"):
        return {"key": key, "topic": topic, "at": 50, "title": "Level 4!", "body": "You reached level 4."}

    def offer(self, item=None, summary=None):
        self.presenter._offer(self.api, [item or self.item()], summary)
        self.flush()

    def transition(self, new, old):
        self.mw.state = new
        self.presenter._transition(new, old)
        self.flush()

    def conquest(self):
        self.offer(self.item("conquered:50", "conquered"))
        self.transition("overview", "review")
        return self.presenter._card._conquest

    def test_review_defers_every_win_and_one_card_merges_the_recap(self):
        self.offer()
        self.offer(self.item("goal:2", "goal"))
        self.assertIsNone(self.presenter._card)
        self.transition("overview", "review")
        card = self.presenter._card
        self.assertEqual("and 1 more", card._more.text())
        self.offer(self.item("goal:2", "goal"), {"reviews": 12, "minutes": 2, "remaining": 3})
        self.assertIs(card, self.presenter._card)
        self.assertIn("12 reviews", card._session.text())
        card._quiet.click()
        self.addon.save_config.assert_called_once_with({"session_summary": False})
        card._continue.click()
        self.addon.home.continue_studying.assert_called_once_with()
        self.assertEqual(0, self.presenter._count())

    def test_starting_review_defers_an_open_card_without_consuming_it(self):
        self.offer()
        self.transition("deckBrowser", "review")
        first = self.presenter._card
        self.transition("review", "deckBrowser")
        self.assertIsNone(self.presenter._card)
        self.assertEqual(1, self.presenter._count())
        self.transition("overview", "review")
        self.assertIsNot(first, self.presenter._card)
        self.presenter._card._dialog.close()
        self.offer(self.item("goal:2", "goal"))
        self.assertIsNone(self.presenter._card, "late wins wait after the session's one card was dismissed")
        self.presenter._open()
        self.assertEqual("goal:2", self.presenter._card._items[0]["key"])

    def test_moments_wait_while_aki_greets(self):
        self.mw.state = "deckBrowser"
        self.presenter._hold()
        self.offer(self.item("goal:2", "goal"))
        self.transition("deckBrowser", None)
        self.assertIsNone(self.presenter._card)

        # Closing the greeting shows what arrived meanwhile.
        self.presenter._release()
        self.flush()
        self.assertEqual("goal:2", self.presenter._card._items[0]["key"])

    def test_a_late_permission_reply_cannot_cross_profiles_or_accounts(self):
        self.defer = True
        self.offer()
        old = self.mw.pm.profile
        self.mw.pm.profile = {}
        self.transition("overview", "review")
        self.complete(self.tasks.pop(0))
        self.flush()
        self.assertIsNone(self.presenter._card)
        self.assertEqual(1, len(ui.moments._pending(old, (self.api.base, self.api.user))))
        self.mw.pm.profile = old
        self.api = SimpleNamespace(**dict(vars(self.api), user="other"))
        self.assertEqual(0, self.presenter._count())

    def test_a_new_session_waits_for_the_current_celebration_preference(self):
        self.offer()
        self.transition("overview", "review")
        self.presenter._card._dialog.close()
        self.transition("review", "overview")
        self.defer = True
        self.api.deck_settings = lambda: {"celebrations": False}
        self.offer(self.item("level:5"))
        self.transition("overview", "review")
        self.assertIsNone(self.presenter._card)
        self.complete(self.tasks.pop(0))
        self.flush()
        self.assertIsNone(self.presenter._card)
        self.assertEqual(1, self.presenter._count())

    def test_disabling_daily_cues_keeps_the_server_streak_in_the_badge(self):
        self.addon.config = lambda: {"goal_celebrations": False}
        self.offer(self.item("secured:2", "secured"))
        self.transition("overview", "review")
        self.assertIsNone(self.presenter._card)
        self.assertEqual(1, self.presenter._count())
        self.presenter._open()
        self.assertIsNotNone(self.presenter._card)

    def test_disabled_server_celebrations_do_not_swallow_a_session_recap(self):
        self.api.deck_settings = lambda: {"celebrations": False}
        self.offer()
        summary = {"reviews": 2, "minutes": 1, "remaining": 3}
        self.offer(dict(self.item("session:50", "session"), local=True, summary=summary), summary)
        self.transition("overview", "review")
        card = self.presenter._card
        self.assertIsNotNone(card)
        self.assertEqual("session:50", card._choices.currentData())
        self.assertEqual("Frozen — streak kept", card._day.text())
        self.assertIn("#def0ff", card._day.styleSheet())
        card._dialog.close()
        self.assertEqual(1, self.presenter._count(), "the disabled server win remains available manually")

    def test_a_queued_local_streak_title_refreshes_when_opened(self):
        summary = {"reviews": 2, "minutes": 1, "remaining": 0}
        self.offer(dict(self.item("secured:50", "secured"), local=True, summary=summary), summary)
        self.transition("overview", "review")
        self.assertEqual("Streak minimum reached — syncing", self.presenter._card._title.text())
        self.transition("review", "overview")
        self.addon.home._streak_title.return_value = "Streak secured! 🔥"
        self.transition("overview", "review")
        self.assertEqual("Streak secured! 🔥", self.presenter._card._title.text())
        self.addon.home._streak_title.assert_called_with(summary)

    def joined(self, unread=True):
        return {"key": "companion:cow", "topic": "companion", "at": 60, "title": "Bluma joined you!",
                "body": "You have studied for 10 hours in total.", "notice": 5, "unread": unread}

    def test_a_companion_that_joined_is_revealed_before_the_card(self):
        self.addon.choose_companion = Mock()
        self.offer(self.joined())
        self.offer()
        self.transition("overview", "review")
        reveal = self.presenter._reveal
        self.assertIsNotNone(reveal)
        self.assertIsNone(self.presenter._card, "the card waits for the reveal")
        self.assertIs(ui._Phase.REVEALING, self.presenter._phase)
        reveal._skip()
        reveal.choose.click()
        self.flush()
        api, companion, _run = self.addon.choose_companion.call_args.args
        self.assertEqual((self.api, "cow"), (api, companion))
        self.assertIn(("/api/activity/sam/read", {"ids": [5]}, None), self.requests)
        self.assertEqual(["level:4"], [item["key"] for item in self.presenter._card._items])

    def test_the_full_reveal_plays_unless_reduce_motion_is_on(self):
        self.mw.pm.reduce_motion = lambda: True
        self.offer(self.joined())
        self.transition("overview", "review")
        self.assertIs(ui.reveal_ui.Phase.FALLING, self.presenter._reveal.reveal.phase, "Anki's own setting does not count")
        self.transition("review", "overview")
        self.addon.config = lambda: {"reduce_motion": True}
        self.transition("overview", "review")
        self.assertIs(ui.reveal_ui.Phase.FADING, self.presenter._reveal.reveal.phase)

    def test_a_moment_read_on_another_device_shows_the_card(self):
        self.offer(self.joined(unread=False))
        self.transition("overview", "review")
        self.assertIsNone(self.presenter._reveal)
        self.assertEqual(["companion:cow"], [item["key"] for item in self.presenter._card._items])

    def test_studying_closes_the_reveal_and_it_plays_again_later(self):
        self.offer(self.joined())
        self.transition("overview", "review")
        first = self.presenter._reveal
        self.transition("review", "overview")
        self.assertIsNone(self.presenter._reveal)
        self.assertEqual([], self.requests)
        self.assertEqual(1, self.presenter._count())
        self.transition("overview", "review")
        self.assertIsNotNone(self.presenter._reveal)
        self.assertIsNot(first, self.presenter._reveal)
        self.presenter._reveal.later.click()
        self.flush()
        self.assertEqual(0, self.presenter._count())
        self.assertIsNone(self.presenter._card)

    def revealed(self):
        self.offer(self.joined())
        self.transition("overview", "review")
        reveal = self.presenter._reveal
        reveal._skip()
        return reveal

    def switch_account(self):
        self.api = SimpleNamespace(**dict(vars(self.api), token="new-token"))

    def test_choose_after_an_account_change_saves_nothing(self):
        self.addon.choose_companion = Mock()
        reveal = self.revealed()
        self.switch_account()
        reveal.choose.click()
        self.flush()
        self.addon.choose_companion.assert_not_called()

    def test_a_queued_choose_is_dropped_after_an_account_change(self):
        self.addon.choose_companion = Mock()
        reveal = self.revealed()
        reveal.choose.click()
        api, companion, run = self.addon.choose_companion.call_args.args
        self.assertEqual(("token", "cow"), (api.token, companion))

        # The save waits in the task queue while the account changes.
        saved, done = [], Mock()
        self.defer = True
        run(lambda: saved.append(companion), done)
        self.switch_account()
        while self.tasks:
            self.complete(self.tasks.pop(0))
        self.assertEqual([], saved)
        done.assert_not_called()

    def test_a_queued_read_is_dropped_after_an_account_change(self):
        reveal = self.revealed()
        self.defer = True
        reveal.later.click()
        self.flush()
        self.switch_account()
        while self.tasks:
            self.complete(self.tasks.pop(0))
        self.assertNotIn("/api/activity/sam/read", [path for path, _body, _method in self.requests])

    def test_a_greeting_that_opens_over_the_reveal_still_holds_the_card(self):
        self.offer()
        reveal = self.revealed()
        self.presenter._hold()
        reveal.later.click()
        self.flush()
        self.assertIsNone(self.presenter._card, "the card waits for the greeting")
        self.presenter._release()
        self.flush()
        self.assertEqual(["level:4"], [item["key"] for item in self.presenter._card._items])

    def test_a_greeting_that_closes_first_keeps_the_reveal_in_front(self):
        self.offer()
        reveal = self.revealed()
        self.presenter._hold()
        self.presenter._release()
        self.flush()
        self.assertIsNone(self.presenter._card, "the card waits for the reveal")
        reveal.later.click()
        self.flush()
        self.assertEqual(["level:4"], [item["key"] for item in self.presenter._card._items])

    def test_conquest_load_is_read_only_and_a_new_win_keeps_the_draft_label(self):
        control = self.conquest()
        self.assertEqual("der Hund", control._label.text())
        self.assertEqual([("/api/conquests/sam/50", None, None)], self.requests)
        self.assertIn("5 lapses · 20 answers", control._stats.text())
        control._label.setText("my unsaved words")
        control._label.setModified(True)
        self.offer(self.item("level:5"))
        self.assertIs(control, self.presenter._card._conquest)
        self.assertEqual("my unsaved words", control._label.text())
        control._copy.click()
        self.assertNotIn("my unsaved words", QApplication.clipboard().text())
        control._save.click()
        self.assertIn(("/api/conquests/sam/50/label", {"label": "my unsaved words"}, None), self.requests)
        control._remove.click()
        self.assertIn(("/api/conquests/sam/50/label", None, "DELETE"), self.requests)

    def test_tell_and_undo_use_the_conquest_endpoint_and_conflict_closes_the_window(self):
        control = self.conquest()
        control._tell.click()
        self.assertTrue(control._undo.isEnabled())
        self.assertFalse(control._tell.isEnabled())
        error = RuntimeError("a friend answered")
        error.status = 409
        self.api._request = Mock(side_effect=error)
        control._undo.click()
        self.assertFalse(control._undo.isEnabled())
        self.assertIn("too late", self.presenter._card._status.text())
        self.api._request.assert_called_once_with("/api/conquests/sam/50/tell", method="DELETE")

    def test_an_expired_undo_never_sends_a_delete(self):
        self.found.update(told=True, undo_until=int(time.time() * 1000) - 1)
        control = self.conquest()
        self.assertFalse(control._undo.isEnabled())
        control._retract()
        self.assertEqual(1, len(self.requests))

    def test_a_local_picture_is_available_before_the_worker_keeps_a_win(self):
        self.found["win"] = None
        control = self.conquest()
        self.assertTrue(control._image.isEnabled())
        self.assertTrue(control._file.isEnabled())
        self.assertFalse(control._link.isEnabled())
        self.found["win"] = 9
        control._retry.click()
        self.assertTrue(control._image.isEnabled())
        control._copy.click()
        self.assertIn("I finally learned a card I had forgotten 5 times.", QApplication.clipboard().text())
        self.assertIn("From my deck “German”.", QApplication.clipboard().text())
        self.assertIn("/conquered/sam/50", QApplication.clipboard().text())

    def test_removing_a_label_cancels_an_older_picture_request(self):
        self.found["label"] = "shared words"
        control = self.conquest()
        self.defer = True
        with patch.object(ui.share_ui.share, "card", side_effect=OSError("offline")):
            control._image.click()
            pending = self.tasks.pop()
            self.defer = False
            control._remove.click()
            self.assertIsNone(control._found["label"])
            QApplication.clipboard().clear()
            self.complete(pending)
        self.assertTrue(QApplication.clipboard().image().isNull(), "the old label must not be exported")

    def test_removed_and_unsaved_labels_never_enter_a_new_local_picture(self):
        self.found["label"] = "shared words"
        control = self.conquest()
        control._remove.click()
        control._label.setText("private draft")
        control._label.setModified(True)
        renderer = load_in_package("moments_qt", "share_picture")
        with patch.object(ui.share_ui.share, "card", side_effect=OSError("offline")), \
                patch.object(renderer, "render", wraps=renderer.render) as draw:
            control._image.click()
        self.assertEqual(1, draw.call_count)
        content = draw.call_args.args[0]
        self.assertNotIn("shared words", content["body"])
        self.assertNotIn("private draft", content["body"])

    def test_late_replies_cannot_write_a_closed_or_switched_card(self):
        control = self.conquest()
        self.defer = True
        control._save.click()
        self.presenter._card._dialog.close()
        self.complete(self.tasks.pop(0))
        self.assertEqual([], self.tasks, "no follow-up load from a closed card")
        self.assertIsNone(self.presenter._card)

    def test_a_later_server_row_adds_sharing_to_a_local_moment(self):
        item = dict(self.item("secured:2", "secured"), local=True)
        self.mw.state = "overview"
        self.offer(item)
        card = self.presenter._card
        self.assertNotIn("Tell friends", [button.text() for button in card._dialog.findChildren(QPushButton)])
        enriched = dict(item, share={"title": "My streak", "body": "Today counts", "win": 7})
        self.offer(enriched)
        self.assertIs(card, self.presenter._card)
        self.assertIn("Tell friends", [button.text() for button in card._dialog.findChildren(QPushButton)])

    def test_switching_accounts_drops_an_old_action_reply_without_consuming_the_win(self):
        control = self.conquest()
        old_profile, old_api = self.mw.pm.profile, self.api
        self.defer = True
        control._save.click()
        self.api = SimpleNamespace(**dict(vars(self.api), token="new-token"))
        self.complete(self.tasks.pop(0))
        self.assertEqual([], self.tasks)
        self.assertFalse([path for path, _body, _method in self.requests if path.endswith("/label")], "the queued save never starts")
        self.presenter._sync_owner()
        self.assertIsNone(self.presenter._card)
        self.assertEqual(1, len(ui.moments._pending(old_profile, (old_api.base, old_api.user))))

    def test_a_deck_name_is_editable_remembered_and_stays_local(self):
        self.mw.col.decks.name = lambda _did: "5 Archive::Spanish::Animals"
        control = self.conquest()
        self.assertEqual("Animals", control._deck_name.currentText())
        choices = [control._deck_name.itemText(index) for index in range(control._deck_name.count())]
        self.assertIn("Spanish", choices)
        self.assertNotIn("Archive", choices)
        requests = deepcopy(self.requests)
        control._deck_name.lineEdit().textEdited.emit("My Spanish words")
        self.assertIn("My Spanish words", control._win()["body"])
        control._load()
        self.assertEqual("My Spanish words", control._deck_name.currentText())
        if capture := environ.get("ANKIQUEST_QT_CAPTURE"):
            if font := environ.get("ANKIQUEST_QT_FONT"):
                family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(font))[0]
                self.presenter._card._dialog.setFont(QFont(family, 10))
            control._share.click()
            self.presenter._card._dialog.resize(480, 640)
            self.flush()
            self.assertTrue(self.presenter._card._dialog.grab().save(str(Path(capture) / "friendly-deck-name.png")))
        self.assertTrue(all(body is None for _path, body, _method in self.requests[len(requests):]))
        self.mw.col.decks.name = lambda _did: "Archive::Old"
        control._load()
        self.assertEqual("Spanish::Animals", control._deck_record["path"].removeprefix("5 Archive::"))
        control._deck_name.lineEdit().textEdited.emit("")
        self.assertNotIn(" in ", control._win()["body"])

    def test_unlock_and_conquest_shares_open_the_recipient_picker(self):
        self.api.capabilities = lambda: {"share_moments", "share_undo_send"}
        request = self.api._request
        self.api._request = lambda path, body=None, method=None: (
            {"friends": [{"user": "ana", "display": "Ana"}], "groups": []}
            if path.startswith("/api/social/") else request(path, body, method))
        with patch.object(ui.share_ui.share, "card", side_effect=OSError("offline")):
            self.offer(dict(self.item("companion_unlocked:ankilope", "companion_unlocked"),
                            share={"title": "Ankilope unlocked", "body": "Level 30", "win": 17}))
            self.transition("overview", "review")
            card = self.presenter._card
            next(button for button in card._dialog.findChildren(QPushButton) if button.text() == "Tell friends").click()
            self.flush()
            opened = next(dialog for dialog in card._dialog.findChildren(QDialog) if hasattr(dialog, "_picker"))
            self.assertEqual(17, opened._picker._win["win"])
            self.assertTrue(opened._picker._form.isVisible())
            opened.close()
            self.presenter._clear()
            self.mw.state = "review"
            control = self.conquest()
            self.assertTrue(control._deck_name.isVisible())
            control._deck_name.lineEdit().textEdited.emit("My vocabulary")
            control._tell.click()
            self.flush()
            opened = next(dialog for dialog in self.presenter._card._dialog.findChildren(QDialog) if hasattr(dialog, "_picker"))
            self.assertEqual(50, opened._picker._win["conquest"])
            self.assertIn("My vocabulary", opened._picker._win["body"])
            self.assertTrue(opened._picker._form.isVisible())
            self.assertFalse(any(path.endswith("/tell") for path, _, _ in self.requests))
            opened.close()

    def test_share_loading_survives_selecting_another_moment(self):
        self.api.capabilities = lambda: {"share_moments", "share_undo_send"}
        request = self.api._request
        self.api._request = lambda path, body=None, method=None: (
            {"friends": [{"user": "ana", "display": "Ana"}], "groups": []}
            if path.startswith("/api/social/") else request(path, body, method))
        with patch.object(ui.share_ui.share, "card", side_effect=OSError("offline")):
            self.offer(dict(self.item(), share={"title": "Level 4", "body": "A win", "win": 17}))
            self.offer(self.item("goal:2", "goal"))
            self.transition("overview", "review")
            card = self.presenter._card
            card._choices.setCurrentIndex(card._choices.findData("level:4"))
            self.defer = True
            next(button for button in card._dialog.findChildren(QPushButton) if button.text() == "Tell friends").click()
            self.complete(self.tasks.pop(0))
            self.flush()
            opened = next(dialog for dialog in card._dialog.findChildren(QDialog) if hasattr(dialog, "_picker"))
            card._choices.setCurrentIndex(card._choices.findData("goal:2"))
            self.complete(self.tasks.pop(0))
            self.assertTrue(opened._picker._form.isVisible())
            self.assertEqual(17, opened._picker._win["win"])
            opened.close()

    def completion(self):
        self.api.capabilities = Mock(return_value={"share_moments", "share_deck_moment", "share_undo_send"})
        self.api.deck_settings = lambda: {"celebrations": True, "decks": [], "recipients": [{"user": "ana"}]}
        summary = {"reviews": 2, "minutes": 1, "remaining": 0, "finished_at": int(time.time() * 1000),
                   "deck": {"id": "5", "path": "01 Languages::Spanish::Animals"}}
        self.offer(dict(self.item("session:50", "session"), local=True, summary=summary), summary)
        self.transition("overview", "review")
        return self.presenter._card._completion

    def test_completed_deck_uses_clean_editable_name_and_picker(self):
        module = ui.deck_moments_ui
        with patch.object(module.deck_moments, "_finished", side_effect=lambda _col, record, _at: record):
            control = self.completion()
        self.assertTrue(control._widget.isVisible())
        self.assertEqual("Animals", control._name.text())
        control._name.setText("My Spanish words")
        self.api._request = Mock(return_value={"friends": [{"user": "ana", "display": "Ana"}], "groups": []})
        control._share.click()
        self.flush()
        opened = next(dialog for dialog in self.presenter._card._dialog.findChildren(QDialog) if hasattr(dialog, "_picker"))
        self.assertEqual({"id": "5", "name": "My Spanish words"}, opened._picker._win["deck"])
        self.assertIn("My Spanish words", opened._picker._win["body"])
        self.assertFalse(opened._picker._send.isEnabled())
        self.assertFalse(any(call.args[1:] for call in self.api._request.call_args_list))
        opened.close()

    def test_completed_deck_check_cannot_outlive_profile_or_window(self):
        module = ui.deck_moments_ui
        with patch.object(module.deck_moments, "_finished", side_effect=lambda _col, record, _at: record) as checked:
            self.defer = True
            control = self.completion()
            self.assertFalse(control._widget.isVisible())
            self.mw.pm.profile = {}
            while self.tasks:
                self.complete(self.tasks.pop(0))
            checked.assert_not_called()
            self.api.capabilities.assert_not_called()
        self.presenter._clear()

    def test_completed_deck_stays_hidden_when_unavailable(self):
        module = ui.deck_moments_ui
        with patch.object(module.deck_moments, "_finished", return_value=None):
            control = self.completion()
        self.assertFalse(control._widget.isVisible())
        self.api.capabilities.assert_not_called()

    def test_completed_deck_check_stops_when_recap_closes(self):
        module = ui.deck_moments_ui
        with patch.object(module.deck_moments, "_finished", side_effect=lambda _col, record, _at: record) as checked:
            self.defer = True
            self.completion()
            self.presenter._card._dialog.close()
            self.flush()
            while self.tasks:
                self.complete(self.tasks.pop(0))
            checked.assert_not_called()
            self.api.capabilities.assert_not_called()

    def test_old_server_and_automatic_decks_keep_the_existing_recap(self):
        module = ui.deck_moments_ui
        for kind in ("old", "automatic", "opted_out"):
            self.presenter._clear()
            self.mw.state = "review"
            self.defer = True
            with patch.object(module.deck_moments, "_finished", side_effect=lambda _col, record, _at: record):
                control = self.completion()
                if kind == "old":
                    self.api.capabilities.return_value = {"share_moments"}
                elif kind == "automatic":
                    self.api.deck_settings = lambda: {"celebrations": True, "recipients": [{"user": "ana"}],
                                                     "decks": [{"id": "5", "enabled": True, "recipients": ["ana"]}]}
                else:
                    self.addon.config = lambda: {"session_summary": False}
                    # A new recap applies its opt-out before starting collection work.
                    control._key = None
                    control._update(self.presenter._card._summary)
                while self.tasks:
                    self.complete(self.tasks.pop(0))
                self.assertFalse(control._widget.isVisible(), kind)

    def test_a_stale_local_deck_reply_cannot_change_another_account(self):
        control = self.conquest()
        previous = self.mw.pm.profile
        ui.conquests_ui.deck_names._state(previous, self.api)["conquests"] = {}
        self.defer = True
        control._load()
        self.mw.pm.profile = {}
        for task in list(self.tasks):
            self.complete(task)
        self.assertNotIn("ankiquestConquestDecks", self.mw.pm.profile)
        self.assertFalse(previous.get("ankiquestConquestDecks", {}).get(self.api.base, {}).get(self.api.user, {}).get("conquests"))

    def test_long_deck_quick_picks_do_not_widen_the_small_window(self):
        self.mw.col.decks.name = lambda _did: "Languages::" + "A very long deck name " * 20
        control = self.conquest()
        control._share.click()
        dialog = self.presenter._card._dialog
        dialog.resize(480, 640)
        self.flush()
        self.assertLessEqual(dialog.width(), 480)
        self.assertEqual(0, dialog.findChild(QScrollArea).horizontalScrollBar().maximum())

    def test_expanded_actions_fit_a_small_window_with_a_fixed_footer(self):
        control = self.conquest()
        card = self.presenter._card
        control._share.click()
        card._dialog.resize(480, 640)
        self.flush()
        scroll = card._dialog.findChild(QScrollArea)
        self.assertEqual(0, scroll.horizontalScrollBar().maximum())
        done = next(button for button in card._dialog.findChildren(QPushButton) if button.text() == "Done")
        self.assertTrue(done.isVisible())
        self.assertIs(card._dialog, done.parentWidget())

    def test_real_anki_templates_and_clozes_produce_the_local_label(self):
        with tempfile.TemporaryDirectory() as folder:
            col = Collection(str(Path(folder) / "collection.anki2"))
            try:
                model = col.models.new("Vocabulary")
                for name in ("ID", "German", "English"):
                    col.models.add_field(model, col.models.new_field(name))
                template = col.models.new_template("Card")
                template.update(qfmt="{{German}}", afmt="{{FrontSide}}<hr>{{English}}")
                col.models.add_template(model, template)
                col.models.add(model)
                note = col.new_note(model)
                note.fields = ["B1L02", "<b>der&nbsp;Hund</b>[sound:hund.mp3]", "the dog"]
                col.add_note(note, 1)
                cloze = col.new_note(col.models.by_name("Cloze"))
                cloze.fields[0] = "{{c1::Paris::city}} is the capital of France"
                col.add_note(cloze, 1)
                for at, entry, expected in ((50, note, "der Hund"), (51, cloze, "Paris is the capital of France")):
                    cid = entry.cards()[0].id
                    col.db.execute("insert into revlog values (?, ?, 0, 3, 25, 8, 2500, 7000, 1)", at, cid)
                    self.assertEqual(expected, ui.conquests_ui.conquests._local(col, at)[0])
            finally:
                col.close()


if __name__ == "__main__":
    unittest.main()
