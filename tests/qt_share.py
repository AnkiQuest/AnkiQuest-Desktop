"""Real recipient controls, delayed requests, profile ownership and share receipts."""

from concurrent.futures import Future
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch

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
OUTDATED = load_in_package("share_qt", "client").OUTDATED
ui.tr = ui.share_ui.tr = lambda text: text
picture = load_in_package("share_picture_qt", "share_picture")
STREAKS = json.loads((Path(__file__).parent / "fixtures/streak_moods.json").read_text("utf-8"))


class ShareWindow(unittest.TestCase):
    def test_old_notice_and_deck_wait_for_chosen_send(self):
        for reference, feature in (({"notification": 42}, "share_notification"),
                                   ({"deck": {"id": "7", "name": "My Japanese"}}, "share_deck_moment")):
            with self.subTest(feature=feature):
                self.win = dict(reference, title="My study moment", body="A completed session.")
                self.features.add(feature)
                self.requests.clear()
                self.delivered.clear()
                window = self.open()
                self.assertEqual(ui._Phase.READY, window._phase)
                self.assertFalse(window._send.isEnabled())
                self.assertFalse(any(body and "moment" in body for _, body, _ in self.requests))
                self.tap(window, "user:cerro")
                window._note.setText("Proud of this")
                window._send.click()
                sent = next(body for _, body, _ in self.requests if body and "moment" in body)
                self.assertEqual(reference, sent["moment"])
                self.assertEqual({"friends": ["cerro"], "groups": []}, sent["to"])
                self.assertEqual("Proud of this", sent["note"])
                self.assertTrue(window._undo.isVisible())
                window._undo.click()
                self.assertEqual({}, self.delivered)
                window._dialog.close()

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

    def test_a_search_without_matches_says_so(self):
        # Android's share sheet keeps "All friends" and names the empty search.
        window = self.open()
        self.assertFalse(window._no_match.isVisible())
        window._search.setText("nobody here")
        self.assertTrue(window._rows[0][1].isVisible())
        self.assertFalse(any(check.isVisible() for _, check in window._rows[1:]))
        self.assertTrue(window._no_match.isVisible())
        self.assertEqual("No friend or group has that name.", window._no_match.text())
        window._search.setText("ana")
        self.assertFalse(window._no_match.isVisible())

    def test_sending_says_sending(self):
        window = self.open()
        self.tap(window, "user:ana")
        self.defer = True
        window._send.click()
        self.assertEqual("Sending…", window._status.text())
        self.complete(self.tasks.pop())
        self.assertIn("Shared with 1 friend", window._status.text())

    def test_friends_that_fail_to_load_point_to_other_apps(self):
        def offline(path, body=None, method=None):
            raise OSError("offline")

        # Same line as Android's share sheet: no Retry, "More apps…" stays.
        self.api._request = offline
        window = self.open()
        self.assertIs(window._phase, ui._Phase.ERROR)
        self.assertEqual("Couldn't load your friends. Check your connection, or share with another app.",
                         window._status.text())
        self.assertFalse(any(isinstance(button, ui.QPushButton) and button.isVisible() and button.text() == "Retry"
                             for button in window._dialog.findChildren(ui.QPushButton)))
        self.assertTrue(window._more.isVisible())

    def test_second_send_undo_preserves_the_first_recipient(self):
        self._two_sends()

    def test_place_picker_and_undo(self):
        self.features.add("share_place")
        self.win = {"place": 2, "title": "Second place", "body": "A good study week"}
        window = self.open()
        self.assertIs(window._phase, ui._Phase.READY)
        self.tap(window, "user:ana")
        window._note.setText("A good study week")
        window._send.click()
        self.assertEqual({"moment": {"place": 2}, "to": {"friends": ["ana"], "groups": []},
                          "note": "A good study week"}, self.requests[-1][1])
        self.assertEqual({"ana"}, set(self.delivered))
        self.assertTrue(window._undo.isVisible())
        window._undo.click()
        self.assertEqual({}, self.delivered)

    def place_sharing(self):
        return SimpleNamespace(owned=lambda: True, api=self.api, win={"place": 2},
                               status=Mock(), dialog=self.parent, _companion="none",
                               current_client=lambda: self.current, run=self.run_task)

    def test_place_routing(self):
        sharing = self.place_sharing()
        legacy = Mock()
        with patch.object(ui.share_ui, "win_dialog") as opened:
            ui.share_ui._route(sharing, legacy)
            legacy.assert_called_once()
            opened.assert_not_called()
            legacy.reset_mock()
            self.features.add("share_place")
            ui.share_ui._route(sharing, legacy)
            legacy.assert_not_called()
            opened.assert_called_once()
            opened.return_value.show.assert_called_once()

    def test_place_routing_falls_back_when_capabilities_fail(self):
        def offline():
            raise OSError("offline")

        # Without the server's features the place goes out the old way, as on an older server.
        self.api.capabilities = offline
        sharing = self.place_sharing()
        legacy = Mock()
        with patch.object(ui.share_ui, "win_dialog") as opened:
            ui.share_ui._route(sharing, legacy)
        legacy.assert_called_once()
        opened.assert_not_called()
        sharing.status.setText.assert_not_called()

    def test_stale_capabilities_do_not_retract_the_first_send(self):
        self.features = {"share_moments"}
        self._two_sends()

    def test_failed_undo_keeps_the_send_and_can_retry(self):
        window = self.open()
        self.tap(window, "user:ana")
        window._send.click()
        receipt = window._phase
        with patch.object(ui.model, "_retract", side_effect=RuntimeError("offline")):
            window._undo.click()
        self.assertIn("Couldn't undo", window._status.text())
        self.assertIs(window._phase, receipt)
        self.assertTrue(window._undo.isEnabled())
        self.assertEqual({"ana"}, set(self.delivered))
        window._undo.click()
        self.assertEqual({}, self.delivered)

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

    def test_an_older_server_asks_for_an_update(self):
        self.features = set()
        window = self.open()
        self.assertIs(window._phase, ui._Phase.ERROR)
        self.assertEqual([], self.requests)
        self.assertEqual(OUTDATED, window._status.text())

    def test_a_win_without_a_reference_shows_only_the_exports(self):
        self.win = {"title": "Level 4!", "body": "", "kind": "level"}
        window = self.open()
        self.assertIs(window._phase, ui._Phase.EXPORT_ONLY)
        self.assertEqual([], self.requests)
        self.assertTrue(window._exports.isVisible())

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

    def test_streak_preview_and_export_keep_the_heat_design_online(self):
        self.win = ui.share.win_from_entry({"id": 42, "win": 17, "kind": "celebration", "topic": "streak",
                                           "moment": "streak:2026-01-01:30", "title": "A month of study", "body": ""})
        with patch.object(ui.share, "card", return_value={"png": self.png}) as fetch:
            window = self.open()
            window._sharing.to_clipboard()
            image = app.clipboard().image()
            self.assertEqual(1080, image.width())
            self.assertEqual(QColor("#DC2626"), image.pixelColor(0, 0))
            fetch.assert_not_called()
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

    def test_streak_unit_matches_phone(self):
        units = {
            "en": ("day streak", "day streak"),
            "es": ("día de racha", "días de racha"),
            "de": ("Tag Lernserie", "Tage Lernserie"),
            "fr": ("jour de série", "jours de série"),
            "pt": ("dia de sequência", "dias de sequência"),
        }
        for language, expected in units.items():
            for days, unit in zip((1, 30), expected):
                with self.subTest(language=language, days=days), patch("anki.lang.current_lang", language), \
                        patch.object(picture, "_words", wraps=picture._words) as words:
                    self.image({"title": "A good day", "picture_streak": days})
                    self.assertIn(unit, [call.args[0] for call in words.call_args_list])

    def test_repeated_streak_body_hidden(self):
        for body in ("30 day streak", "One more day of practice"):
            with self.subTest(body=body), patch("anki.lang.current_lang", "en"), \
                    patch.object(picture, "_words", wraps=picture._words) as words:
                self.image({"title": "A good day", "body": body, "picture_streak": 30})
                text = [call.args[0] for call in words.call_args_list]
                if body == "30 day streak":
                    self.assertNotIn(body, text)
                else:
                    self.assertIn(body, text)

    def test_streak_heat_and_next_milestones_match_shared_cases(self):
        for case in STREAKS["pictures"]:
            with self.subTest(streak=case["streak"]), patch.object(picture, "_words", wraps=picture._words) as words:
                win = {"title": "My streak", "body": "A little progress", "picture_streak": case["streak"]}
                image = self.image(win)
                self.assertEqual(QColor(case["top"]), image.pixelColor(0, 0))
                self.assertEqual(QColor(case["bottom"]), image.pixelColor(0, image.height() - 1))
                ink = QColor(STREAKS["picture_style"]["ink"])
                self.assertGreater(sum(image.pixelColor(x, y) == ink for y in range(0, image.height(), 8)
                                       for x in range(0, image.width(), 8)), 50)
                text = [str(call.args[0]) for call in words.call_args_list]
                if case["next"] is not None:
                    left = case["next"] - case["streak"]
                    self.assertIn("%d %s to %d" % (left, "day" if left == 1 else "days", case["next"]), text)
                else:
                    self.assertFalse(any(" to " in value for value in text))
                self.assertLessEqual(image.height(), 4096)
                self.assertEqual(case["pose"], picture.moods.streak_pose(picture.moods.FIRE, case["streak"]))

    def test_streak_number_is_gold_localized_and_fits_large_text(self):
        with patch("anki.lang.current_lang", "de"), patch.object(picture, "_words", wraps=picture._words) as words:
            image = self.image({"title": "Meine Lernserie", "picture_streak": 10000}, "aki", scale=2)
            numbers = [call for call in words.call_args_list if call.args[0] == "10.000"]
            self.assertEqual(1, len(numbers))
            layout, _ = picture._words(*numbers[0].args)
            self.assertEqual(1, layout.lineCount())
            self.assertLessEqual(layout.lineAt(0).naturalTextWidth(), 936)
            gold = QColor(STREAKS["picture_style"]["number"])
            self.assertGreater(sum(image.pixelColor(x, y) == gold for y in range(0, image.height(), 4)
                                   for x in range(0, image.width(), 4)), 300)
            folder = os.environ.get("ANKIQUEST_QT_CAPTURE")
            if folder:
                self.assertTrue(image.save(str(Path(folder) / "streak-large-localized.png")))

    def test_streak_art_uses_heat_and_falls_back_to_core_streak(self):
        win = {"title": "My streak", "picture_streak": 30}
        original = picture.companion_art.pixmap
        paths = []

        def missing_tier(path, companion, size):
            paths.append((Path(path).stem, size))
            return original(path, companion, size) if "blazing" not in path else original("missing.png", companion, size)

        with patch.object(picture.companion_art, "pixmap", side_effect=missing_tier):
            self.image(win, "aki")
        hero = STREAKS["picture_style"]["hero"]
        self.assertEqual([("aki_streak_blazing", hero), ("aki_streak", hero)], paths)

    def test_streak_picture_capture(self):
        folder = os.environ.get("ANKIQUEST_QT_CAPTURE")
        for days in (1, 7, 30, 100):
            image = self.image({"title": "I kept showing up", "body": "One day at a time.", "picture_streak": days}, "aki")
            if folder:
                self.assertTrue(image.save(str(Path(folder) / ("streak-%d.png" % days))))

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

    def test_a_missing_extension_keeps_the_companion_in_the_picture(self):
        win = {"title": "A win", "body": "A little progress"}
        expected = self.image(win, "aki")
        self.assertEqual(expected, self.image(dict(win, picture_pose="aki_missing_extension"), "aki"))

    def test_invalid_or_excessive_content_fails_explicitly(self):
        with self.assertRaises(ValueError):
            self.image({"title": "Long", "body": "many words " * 10000})
        with self.assertRaises(ValueError):
            self.image({"title": "Invalid scale"}, scale=0)
        for streak in (0, -1, True, "30", 2_147_483_648):
            with self.subTest(streak=streak), self.assertRaises(ValueError):
                self.image({"title": "Invalid streak", "picture_streak": streak})

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
