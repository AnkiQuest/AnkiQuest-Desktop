"""The countdown forms with real Qt controls, run in a separate process by test_countdowns.py."""
from datetime import date
import unittest
from unittest.mock import Mock, patch

from aqt.qt import QApplication, QComboBox, QDialog, QMessageBox
from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
ui = load_in_package("countdowns_qt", "countdowns_ui")
countdowns = load_in_package("countdowns_qt", "countdowns")
ui.tr = lambda text: text

# Anki accepts deck names longer than a countdown may keep.
LONG_DECK = "D" * (countdowns.MAX_DECK_CHARS + 1)
EXAM = countdowns.Event("Spanish exam", "2026-12-01", "Spanish")


class EventForm(unittest.TestCase):
    def test_the_deck_picker_leaves_out_decks_a_countdown_cannot_keep(self):
        shown = []

        def cancel(dialog):
            picker = dialog.findChild(QComboBox)
            shown.extend(picker.itemData(index) for index in range(picker.count()))
            return 0

        with patch.object(QDialog, "exec", cancel):
            ui._event_dialog(None, "Add countdown", None, ["Spanish", LONG_DECK], date(2026, 11, 20))

        self.assertEqual([None, "Spanish"], shown)


class CountdownList(unittest.TestCase):
    def test_an_event_the_server_would_refuse_is_not_saved(self):
        save, tell = Mock(), Mock()
        dialog = ui.CountdownsDialog(None, [EXAM], ["Spanish", LONG_DECK], date(2026, 11, 20), save)
        refused = countdowns.Event("Driving test", "2027-01-10", LONG_DECK)

        with patch.object(ui, "_event_dialog", return_value=refused), patch.object(ui, "_tell", tell):
            dialog._new()

        # The existing list stays as it was, on screen and on the server.
        save.assert_not_called()
        tell.assert_called_once()
        self.assertEqual([EXAM], dialog._items)
        self.assertEqual(1, dialog._list.count())


class ImportOffer(unittest.TestCase):
    def answer(self, label):
        def click(box):
            next(button for button in box.buttons() if button.text() == label).click()
            return 0

        with patch.object(QMessageBox, "exec", click):
            return ui.ask_import(None, "Add the 2 countdowns you made while signed out to hill?")

    def test_add_to_account_says_yes(self):
        self.assertTrue(self.answer("Add to account"))

    def test_keep_on_this_device_says_no(self):
        self.assertFalse(self.answer("Keep on this device"))


if __name__ == "__main__":
    unittest.main()
