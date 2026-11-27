"""Real Qt checks for the optimize reminder, run by test_qt_windows.py."""

import sys
import unittest
from unittest.mock import Mock, patch

from aqt.qt import QDialog, QLabel, QPushButton, QTimer, QVBoxLayout, QWidget

from addon_loader import load_in_package
from qt_support import app


ui = load_in_package("optimize_reminder_qt", "optimize_reminder_ui")
rule = load_in_package("optimize_reminder_qt", "optimize_reminder")
ui.tr = lambda text: text


class Main(QWidget):
    """Anki's main window as the reminder reads it: a parent with an open collection."""

    col = object()


OPTIMIZED = 1786334400000
NOW = OPTIMIZED + 30 * rule.DAY_MS
DUE = rule.Inputs(now_ms=NOW, last_optimized_ms=OPTIMIZED, reviews_since=1500, presets=[rule.Scheduler.FSRS, rule.Scheduler.RWKV_CURVE], deck=7)


class Reminder(unittest.TestCase):
    def open(self, action, run):
        """Runs `run`, which opens the reminder, with `action` on the dialog; returns run's result."""
        errors, seen = [], []

        def interact():
            dialog = app.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QDialog)
                seen.append(dialog)
                action(dialog)
            except Exception as error:
                errors.append(error)
                dialog.reject()

        QTimer.singleShot(0, interact)
        result = run()
        if errors:
            raise errors[0]
        self.assertEqual(1, len(seen))
        return result

    def button(self, dialog, text):
        return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)

    def test_text_and_buttons_in_the_android_order(self):
        def check(dialog):
            texts = [label.text() for label in dialog.findChildren(QLabel) if label.text()]
            self.assertEqual([rule.TITLE, rule.message(rule.Remind(rule.Since.STALE, rule.Wording.MIXED), str)], texts)
            buttons = sorted(dialog.findChildren(QPushButton), key=lambda button: button.mapTo(dialog, button.rect().topLeft()).x())
            self.assertEqual([rule.SNOOZE, rule.DISMISS, rule.OPEN], [button.text() for button in buttons])
            self.assertTrue(self.button(dialog, rule.OPEN).isDefault())
            dialog.reject()

        choice = self.open(check, lambda: ui.ask(None, rule.Remind(rule.Since.STALE, rule.Wording.MIXED)))
        self.assertIs(ui.Choice.CLOSED, choice)

    def offer(self, config, press):
        saved = []
        mw = Main()
        deckoptions = Mock()
        # The player picks a minute after the dialog opened; a snooze counts from then.
        picked = NOW + 60_000
        with patch.object(rule, "inputs", return_value=DUE), patch.object(rule, "now_ms", return_value=picked), patch.dict(sys.modules, {"aqt.deckoptions": deckoptions}):
            with patch("aqt.deckoptions", deckoptions, create=True):
                self.open(lambda dialog: self.button(dialog, press).click(), lambda: ui.offer(mw, config, saved.append))
        return saved, deckoptions

    def test_snooze_and_dismiss_save_the_next_state(self):
        saved, _ = self.offer({}, rule.SNOOZE)
        self.assertEqual([{rule.CONFIG_KEY: {"kind": "snoozed", "until_ms": NOW + 60_000 + 7 * rule.DAY_MS}}], saved)
        saved, _ = self.offer({}, rule.DISMISS)
        self.assertEqual([{rule.CONFIG_KEY: {"kind": "dismissed", "optimized_ms": OPTIMIZED}}], saved)

    def test_open_shows_deck_options_for_the_current_deck(self):
        saved, deckoptions = self.offer({}, rule.OPEN)
        self.assertEqual([], saved)
        deckoptions.display_options_for_deck_id.assert_called_once_with(7)

    def test_nothing_shows_while_off_or_not_due(self):
        for config, found in (({rule.CONFIG_KEY: {"kind": "off"}}, DUE), ({}, rule.Inputs(NOW, NOW - rule.DAY_MS, 1500, [rule.Scheduler.FSRS], 7))):
            with self.subTest(config=config), patch.object(rule, "inputs", return_value=found), patch.object(ui, "ask") as ask:
                ui.offer(Main(), config, Mock())
                ask.assert_not_called()

    def test_the_switch_turns_off_and_keeps_a_snooze(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        snoozed = {rule.CONFIG_KEY: {"kind": "snoozed", "until_ms": NOW + 7 * rule.DAY_MS}}
        values = ui.settings_switch(layout, snoozed)
        box = holder.findChild(ui.QCheckBox, "ankiquest_optimize_reminder")
        self.assertTrue(box.isChecked())
        self.assertEqual(rule.SETTING, box.text())
        self.assertEqual(snoozed, values())
        box.setChecked(False)
        self.assertEqual({rule.CONFIG_KEY: {"kind": "off"}}, values())

        values = ui.settings_switch(layout, {rule.CONFIG_KEY: {"kind": "off"}})
        self.assertFalse(holder.findChildren(ui.QCheckBox)[-1].isChecked())
        holder.findChildren(ui.QCheckBox)[-1].setChecked(True)
        self.assertEqual({rule.CONFIG_KEY: {"kind": "on"}}, values())


if __name__ == "__main__":
    unittest.main()
