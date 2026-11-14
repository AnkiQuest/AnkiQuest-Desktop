"""Real recipient controls, delayed requests, profile ownership and share receipts."""

from concurrent.futures import Future
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from aqt.qt import QApplication, QBuffer, QByteArray, QFont, QFontDatabase, QImage, QIODevice, QWidget

from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
ui = load_in_package("share_qt", "moment_share_ui")
ui.tr = ui.share_ui.tr = lambda text: text


class ShareWindow(unittest.TestCase):
    def setUp(self):
        self.parent = QWidget()
        self.parent.pm = SimpleNamespace(profile={})
        self.tasks, self.requests, self.delivered, self.windows = [], [], {}, []
        self.defer = False
        self.features = {"share_moments", "share_undo_send"}
        self.api = SimpleNamespace(base="https://quest.test", user="hill", token="test-token",
                                   capabilities=lambda: self.features, _request=self.request)
        self.current = self.api
        self.social = {"friends": [{"user": "ana", "display": "Ana"}, {"user": "cerro", "display": "Cerro"}],
                       "groups": [{"id": 3, "name": "Solo", "members": [{"user": "hill"}]},
                                  {"id": 2, "name": "Night owls", "members": [{"user": "hill"}, {"user": "ana"}]}]}
        self.win = {"win": 17, "title": "Anki-tan unlocked", "body": "A 66-day streak.", "kind": "companion_unlocked"}
        image = QImage(120, 60, QImage.Format.Format_ARGB32)
        image.fill(0xff335577)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        self.png = bytes(data)
        fake = patch.object(ui.share, "card", return_value={"png": self.png})
        fake.start()
        self.addCleanup(fake.stop)

    def tearDown(self):
        for window in self.windows:
            if window._phase is not ui._Phase.CLOSED:
                window._dialog.close()
        self.parent.close()
        app.processEvents()

    def request(self, path, body=None, method=None):
        self.requests.append((path, body, method))
        if path.startswith("/api/social/"):
            return deepcopy(self.social)
        if method == "DELETE":
            stamp = int(path.split("?until=")[1]) if "?until=" in path else None
            removed = [key for key, receipt in self.delivered.items() if stamp is None or stamp == receipt]
            for key in removed:
                self.delivered.pop(key)
            return {"retracted": len(removed)}
        if body and "moment" in body:
            until = int(time.time() * 1000) + 60000 + len(self.requests)
            people = body["to"]["friends"] if isinstance(body["to"], dict) else ["ana", "cerro"]
            for person in people:
                self.delivered[person] = until
            return {"recipients": len(people), "win": 17, "undo_until": until}
        return {"recipients": 2}

    def run_task(self, work, done):
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

    def open(self):
        window = ui._Picker(self.parent, self.api, self.win, "none", lambda: self.current, self.run_task)
        self.windows.append(window)
        window._dialog.show()
        app.processEvents()
        return window

    def tap(self, window, key):
        for target, check in window._rows:
            found = "circle" if target is ui.model._Choice.CIRCLE else target._key
            if key == found:
                check.click()
                return
        self.fail("Missing recipient " + key)

    def test_picker_order_search_exclusivity_note_and_picture(self):
        window = self.open()
        self.assertEqual(["All friends", "Ana", "Cerro", "Night owls"], [check.text() for _, check in window._rows])
        self.assertFalse(window._send.isEnabled())
        self.assertTrue(window._preview.isVisible())
        self.tap(window, "circle")
        self.tap(window, "user:ana")
        self.tap(window, "group:2")
        self.assertFalse(window._rows[0][1].isChecked())
        window._search.setText("night")
        self.assertFalse(window._rows[1][1].isVisible())
        self.assertTrue(window._rows[-1][1].isVisible())
        window._note.setText("\U0001f331" * 141)
        self.assertEqual(140, len(window._note.text()))
        window._send.click()
        sent = self.requests[-1][1]
        self.assertEqual({"moment": {"win": 17}, "to": {"friends": ["ana"], "groups": [2]}, "note": "\U0001f331" * 140}, sent)
        self.assertTrue(window._undo.isVisible())
        self.assertIn("Shared with 1 friend", window._status.text())

    def test_second_send_undo_preserves_the_first_recipient(self):
        self._two_sends()

    def test_stale_capabilities_do_not_retract_the_first_send(self):
        self.features = {"share_moments"}
        self._two_sends()

    def _two_sends(self):
        first = self.open()
        self.tap(first, "user:ana")
        first._send.click()
        second = self.open()
        self.tap(second, "user:cerro")
        second._send.click()
        self.assertEqual({"ana", "cerro"}, set(self.delivered))
        stamp = second._phase._sent._until
        second._undo.click()
        self.assertEqual({"ana"}, set(self.delivered))
        self.assertEqual("/api/share/hill/17?until=%d" % stamp, self.requests[-1][0])

    def test_queued_send_cannot_start_after_signout_or_double_click(self):
        window = self.open()
        self.tap(window, "circle")
        self.defer = True
        window._send.click()
        window._submit()
        self.assertEqual(1, len(self.tasks))
        self.current = SimpleNamespace(base=self.api.base, user="other", token="other")
        self.complete(self.tasks.pop())
        self.assertEqual({}, self.delivered)
        self.assertEqual({}, self.parent.pm.profile)

    def test_late_capabilities_do_not_cross_profiles_or_closed_windows(self):
        self.defer = True
        window = self.open()
        self.parent.pm.profile = {}
        self.complete(self.tasks.pop())
        self.assertEqual([], self.requests)
        self.assertEqual([], window._rows)
        closed = self.open()
        closed._dialog.close()
        self.complete(self.tasks.pop())
        self.assertEqual([], self.requests)
        self.assertIs(closed._phase, ui._Phase.CLOSED)

    def test_late_send_reply_cannot_write_recents_after_close(self):
        window = self.open()
        self.tap(window, "user:ana")
        self.defer = True
        window._send.click()
        work, done = self.tasks.pop()
        future = Future()
        future.set_result(work())
        window._dialog.close()
        done(future)
        self.assertEqual({}, self.parent.pm.profile)

    def test_empty_social_list_offers_an_invitation(self):
        self.social["friends"] = []
        self.social["groups"] = self.social["groups"][:1]
        window = self.open()
        self.assertTrue(window._empty.isVisible())
        self.assertTrue(window._invite.isVisible())
        self.assertFalse(window._send.isEnabled())
        window._invite.click()
        self.assertIn("Study with me on AnkiQuest", app.clipboard().text())

    def test_older_servers_keep_legacy_actions_without_fetching_recipients(self):
        self.features = set()
        window = self.open()
        self.assertIs(window._phase, ui._Phase.LEGACY)
        self.assertEqual([], self.requests)
        self.assertTrue(window._legacy.isVisible())
        window._legacy.click()
        self.assertEqual({"win": 17, "to": "friends"}, self.requests[-1][1])

    def test_more_apps_reuses_the_preview_without_publishing(self):
        window = self.open()
        window._more.click()
        self.assertTrue(window._exports.isVisible())
        window._sharing.to_clipboard()
        self.assertFalse(app.clipboard().image().isNull())
        self.assertFalse(any(body for _, body, _ in self.requests))

    def test_capture_at_normal_and_large_font(self):
        folder = os.environ.get("ANKIQUEST_QT_CAPTURE")
        font = os.environ.get("ANKIQUEST_QT_FONT")
        family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(font))[0] if font else "sans-serif"
        window = self.open()
        for size, name in ((10, "share"), (20, "share-large")):
            window._dialog.setFont(QFont(family, size))
            window._dialog.resize(520, 720)
            app.processEvents()
            self.assertLessEqual(window._dialog.width(), 520)
            if folder:
                self.assertTrue(window._dialog.grab().save(str(Path(folder) / (name + ".png"))))


if __name__ == "__main__":
    unittest.main()
