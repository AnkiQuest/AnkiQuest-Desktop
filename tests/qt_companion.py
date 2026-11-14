"""Real Qt checks of the companion picker, run in a separate process by test_companion_unlock.py."""

from concurrent.futures import Future
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from aqt.qt import QApplication, QImage, QLabel, QPushButton

from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
companion_ui = load_in_package("companion_qt", "companion_ui")
companion_art = load_in_package("companion_qt", "companion_art")
companion_unlock = load_in_package("companion_qt", "companion_unlock")
share = load_in_package("companion_qt", "share")
companion_ui.tr = lambda text: text

UNLOCKS = frozenset([companion_unlock.FEATURE])


class Picker(unittest.TestCase):
    def setUp(self):
        self.prefs = {}
        self.unlocked = []
        self.api = SimpleNamespace(
            base="https://example.test", name="hill",
            capabilities=Mock(return_value=UNLOCKS), companion=Mock(return_value="ankilope"),
            unlocks=Mock(side_effect=lambda: {"unlocks": list(self.unlocked)}),
            unlock=Mock(side_effect=self.unlock), set_companion=Mock(),
        )
        self.mw = SimpleNamespace(pm=SimpleNamespace(profile=self.prefs), taskman=SimpleNamespace(run_in_background=self.run_task))
        self.saved = []

    def unlock(self, unlock):
        self.unlocked.append(unlock)
        return {"unlocks": list(self.unlocked)}

    def run_task(self, work, done):
        future = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        done(future)

    def picker(self):
        return companion_ui.Picker(None, self.mw, self.api, "aki", self.saved.append)

    def cards(self, picker):
        """The cards in the order the picker shows them."""
        row = picker._row
        return [row.itemAt(index).widget().property("companion") for index in range(row.count())]

    def card(self, picker, companion):
        return next(card for card in picker.dialog.findChildren(QPushButton, companion_ui.CARD) if card.property("companion") == companion)

    def message(self, picker):
        return picker.dialog.findChild(QLabel, "ankiquest_companion_message")

    def test_the_cow_is_hidden_until_ankilope_is_tapped_nine_times(self):
        picker = self.picker()
        self.assertEqual(["aki", "ankilope", "none"], self.cards(picker))
        self.assertEqual("ankilope", picker.chosen(), "the account's companion is selected")
        for _ in range(companion_unlock.TAPS - 1):
            self.card(picker, "ankilope").click()
        self.assertEqual(["aki", "ankilope", "none"], self.cards(picker))
        self.card(picker, "ankilope").click()

        self.assertEqual(["aki", "ankilope", "cow", "none"], self.cards(picker))
        self.assertEqual("cow", picker.chosen())
        self.assertEqual("Bluma joined you!", self.message(picker).text())
        self.api.unlock.assert_called_once_with("cow")
        key = companion_unlock.account(self.api)
        self.assertEqual([], companion_unlock.pending(self.prefs, key), "the server has it")

        # Saving the cow sends no second unlock.
        picker._save()
        self.api.set_companion.assert_called_once_with("cow")
        self.api.unlock.assert_called_once_with("cow")
        self.assertEqual(["cow"], self.saved)

    def test_each_card_previews_its_poses(self):
        picker = self.picker()
        for companion, count in (("aki", 3), ("ankilope", 2), ("none", 1)):
            labels = [label for label in self.card(picker, companion).findChildren(QLabel) if label.pixmap() is not None and not label.pixmap().isNull()]
            self.assertEqual(count if companion != "none" else 0, len(labels), companion)

    def test_an_unlock_made_offline_is_kept_and_sent_with_the_cow(self):
        self.api.capabilities.side_effect = OSError("offline")
        picker = self.picker()
        self.api.unlock.side_effect = OSError("offline")
        for _ in range(companion_unlock.TAPS):
            self.card(picker, "ankilope").click()
        self.assertEqual("cow", picker.chosen())
        key = companion_unlock.account(self.api)
        self.assertEqual(["cow"], companion_unlock.pending(self.prefs, key))

        # Back online, saving the cow unlocks it first.
        self.api.capabilities.side_effect = None
        self.api.unlock.side_effect = self.unlock
        picker._save()
        self.assertEqual(["cow"], self.unlocked)
        self.api.set_companion.assert_called_once_with("cow")
        self.assertEqual([], companion_unlock.pending(self.prefs, key))

    def test_a_server_without_unlocks_keeps_the_cow_hidden(self):
        self.api.capabilities.return_value = frozenset()
        picker = self.picker()
        for _ in range(companion_unlock.TAPS):
            self.card(picker, "ankilope").click()
        self.assertEqual(["aki", "ankilope", "none"], self.cards(picker))
        self.api.unlock.assert_not_called()

    def test_an_unlock_from_another_device_shows_the_cow(self):
        self.unlocked.append("cow")
        self.api.companion.return_value = "cow"
        picker = self.picker()
        self.assertEqual(["aki", "ankilope", "cow", "none"], self.cards(picker))
        self.assertEqual("cow", picker.chosen())
        self.assertFalse(self.message(picker).isVisible())

    def test_the_cow_is_ankilope_turned_purple(self):
        face = share.face_path("cow")
        ankilope = companion_art.pixmap(face, "ankilope").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        cow = companion_art.pixmap(face, "cow").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self.assertEqual(ankilope.size(), cow.size())
        self.assertNotEqual(ankilope, cow)

        # Ankilope's tan coat turns a light purple, as CSS hue-rotate(250deg) turns it.
        red, green, blue = companion_art.turn_rgb(companion_art.matrix(250), 234, 171, 91)
        self.assertGreater(blue, green)
        self.assertGreater(red, green)
        art = companion_art.pose_path("ankilope_celebrate")
        turned = companion_art.pixmap(art, "cow").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        plain = QImage(art).convertToFormat(QImage.Format.Format_ARGB32)
        alphas = {(plain.pixelColor(x, 128).alpha(), turned.pixelColor(x, 128).alpha()) for x in range(0, 256, 8)}
        self.assertTrue(all(a == b for a, b in alphas))


if __name__ == "__main__":
    unittest.main()
