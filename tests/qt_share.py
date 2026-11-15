"""Real recipient controls, delayed requests, profile ownership and share receipts."""

from concurrent.futures import Future
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from aqt.qt import QApplication, QBuffer, QByteArray, QColor, QFont, QFontDatabase, QImage, QIODevice, QPalette, QWidget

from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
if os.environ.get("ANKIQUEST_QT_FONT"):
    font = os.environ["ANKIQUEST_QT_FONT"]
    family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(font))[0]
    app.setFont(QFont(family, 10))
    for fallback in os.environ.get("ANKIQUEST_QT_FALLBACKS", "").split(os.pathsep):
        if fallback:
            QFontDatabase.addApplicationFont(fallback)
ui = load_in_package("share_qt", "moment_share_ui")
ui.tr = ui.share_ui.tr = lambda text: text
picture = load_in_package("share_picture_qt", "share_picture")


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

    def test_offline_preview_is_a_local_picture_without_publishing(self):
        with patch.object(ui.share, "card", side_effect=OSError("offline")):
            window = self.open()
            self.assertTrue(window._preview.isVisible())
            window._sharing.to_clipboard()
            image = app.clipboard().image()
            self.assertEqual(1080, image.width())
            self.assertGreaterEqual(image.height(), 1080)
            self.assertFalse(any(body for _, body, _ in self.requests))

    def test_a_cached_picture_cannot_cross_an_account_or_profile_change(self):
        for change in ("account", "profile"):
            with self.subTest(change=change):
                self.current = self.api
                window = self.open()
                app.clipboard().clear()
                if change == "account":
                    self.current = SimpleNamespace(base=self.api.base, user="other", token="other")
                else:
                    self.parent.pm.profile = {}
                window._sharing.to_clipboard()
                self.assertTrue(app.clipboard().image().isNull())

    def test_late_offline_failure_does_not_render_for_a_changed_owner(self):
        window = self.open()
        window._sharing.found = None
        self.defer = True
        window._sharing.to_clipboard()
        work, done = self.tasks.pop()
        future = Future()
        future.set_exception(OSError("offline"))
        self.current = SimpleNamespace(base=self.api.base, user="other", token="other")
        app.clipboard().clear()
        done(future)
        self.assertTrue(app.clipboard().image().isNull())

    def test_a_win_without_a_server_id_still_offers_picture_actions(self):
        self.win = {"title": "My weekly study recap", "body": "A little progress every day.", "notification": 91}
        with patch.object(ui.share, "card", side_effect=AssertionError("no server image exists")) as fetch:
            window = self.open()
            window._more.click()
            actions = [button.text() for button in window._exports.findChildren(ui.QPushButton)]
            self.assertIn("Copy as image", actions)
            self.assertIn("Save image…", actions)
            self.assertNotIn("Copy public link", actions)
            window._sharing.to_clipboard()
            self.assertEqual(1080, app.clipboard().image().width())
            fetch.assert_not_called()

    def test_capture_at_normal_and_large_font(self):
        folder = os.environ.get("ANKIQUEST_QT_CAPTURE")
        font = os.environ.get("ANKIQUEST_QT_FONT")
        family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(font))[0] if font else "sans-serif"
        with patch.object(ui.share, "card", side_effect=OSError("offline")):
            window = self.open()
        for size, name in ((10, "share"), (20, "share-large")):
            window._dialog.setFont(QFont(family, size))
            window._dialog.resize(520, 720)
            app.processEvents()
            self.assertLessEqual(window._dialog.width(), 520)
            if folder:
                self.assertTrue(window._dialog.grab().save(str(Path(folder) / (name + ".png"))))


class LocalPicture(unittest.TestCase):
    def image(self, win, companion="none", palette=None, scale=1):
        found = picture.render(win, companion, palette or app.palette(), scale)
        image = QImage()
        self.assertTrue(image.loadFromData(found["png"], "PNG"))
        return image

    def test_unicode_and_long_words_wrap_without_clipping(self):
        words = "Espa\u00f1ol \u65e5\u672c\u8a9e \U0001f331 " * 35
        win = {"title": "A little progress", "body": words + "\n" + "x" * 120}
        image = self.image(win)
        self.assertEqual(1080, image.width())
        self.assertGreater(image.height(), 1080)
        self.assertLessEqual(image.height(), 4096)
        layout, height = picture._words(words, 42, QFont.Weight.Normal)
        self.assertEqual(len(words.encode("utf-16-le")) // 2, sum(layout.lineAt(i).textLength() for i in range(layout.lineCount())))
        self.assertGreater(height, 42)
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            self.assertLessEqual(line.naturalTextWidth(), 936)

    def test_capture_font_has_real_letter_glyphs(self):
        if not os.environ.get("ANKIQUEST_QT_CAPTURE"):
            return
        layout, _ = picture._words("AnkiQuest \u65e5\u672c\u8a9e", 36, QFont.Weight.Bold)
        glyphs = [index for run in layout.glyphRuns() for index in run.glyphIndexes()]
        self.assertTrue(glyphs, "capture font must draw text")
        self.assertNotIn(0, glyphs, "capture must not substitute missing-glyph boxes")

    def test_hidden_fields_never_enter_the_picture(self):
        win = {"title": "A win", "body": "Only these words"}
        expected = self.image(win)
        supplied = dict(win, token="private-token", label="unsaved label", deck="private deck", fields={"Front": "private"})
        self.assertEqual(expected, self.image(supplied))

    def test_invalid_or_excessive_content_fails_explicitly(self):
        with self.assertRaises(ValueError):
            self.image({"title": "Long", "body": "many words " * 10000})
        with self.assertRaises(ValueError):
            self.image({"title": "Invalid scale"}, scale=0)

    def test_captures_light_dark_and_large_text(self):
        folder = os.environ.get("ANKIQUEST_QT_CAPTURE")
        win = {"title": "I reached level 30", "body": "A little progress, every day. Espa\u00f1ol, \u65e5\u672c\u8a9e."}
        for dark in (False, True):
            palette = QPalette(app.palette())
            background, ink = ("#18212c", "#f2f4f8") if dark else ("#ffffff", "#263247")
            palette.setColor(QPalette.ColorRole.Window, QColor(background))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(ink))
            for scale in (1, 2):
                image = self.image(win, "aki", palette, scale)
                self.assertEqual(QColor(background), image.pixelColor(0, 0))
                self.assertGreaterEqual(image.height(), 1080)
                if folder:
                    name = "offline-%s-%s.png" % ("dark" if dark else "light", scale)
                    self.assertTrue(image.save(str(Path(folder) / name)))
        conquest = load_in_package("share_picture_qt", "conquests")
        found = {"label": "日本語", "conquest": {"at": 864000000, "since": 0, "lapses": 5, "answers": 20}}
        win = conquest._win(SimpleNamespace(base="https://quest.test", user="sam"), 50, found, "My vocabulary", str)
        image = self.image(win, "aki", palette)
        if folder:
            self.assertTrue(image.save(str(Path(folder) / "offline-conquest.png")))


if __name__ == "__main__":
    unittest.main()
