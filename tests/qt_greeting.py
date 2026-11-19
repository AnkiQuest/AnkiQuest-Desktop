"""Real Qt checks for Aki's greeting, run by test_qt_windows.py."""

import unittest

from aqt.qt import QDialog, QLabel, QPushButton, QTimer, Qt

from addon_loader import load_in_package
from qt_support import app


greeting = load_in_package("greeting_qt", "greeting")
greeting.tr = lambda text: text


class Greeting(unittest.TestCase):
    def open(self, account, action):
        """Opens the greeting for `account`, runs `action` on it and returns the choice."""
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
        choice = greeting.ask(None, account)
        if errors:
            raise errors[0]
        self.assertEqual(1, len(seen))
        return choice

    def buttons(self, dialog):
        return [button.text() for button in dialog.findChildren(QPushButton)]

    def button(self, dialog, text):
        return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)

    def texts(self, dialog):
        return [label.text() for label in dialog.findChildren(QLabel) if label.text()]

    def test_aki_introduces_herself_in_the_android_order(self):
        def check(dialog):
            image = next(label for label in dialog.findChildren(QLabel) if label.pixmap() is not None and not label.pixmap().isNull())
            self.assertEqual("Aki waving hello", image.accessibleName())
            self.assertEqual(greeting.IMAGE_SIZE, max(image.pixmap().width(), image.pixmap().height()))
            self.assertEqual(
                ["Hi, I’m Aki!", "AnkiQuest adds streaks, friends and leaderboards to Anki. I’ll keep you company while you study."],
                self.texts(dialog),
            )
            dialog.reject()

        self.open(greeting.Account.SIGNED_OUT, check)

    def test_signed_out_players_are_offered_the_sign_in(self):
        def check(dialog):
            self.assertEqual(["Later", "Sign in"], self.buttons(dialog))
            self.button(dialog, "Sign in").click()

        self.assertIs(greeting.Choice.SIGN_IN, self.open(greeting.Account.SIGNED_OUT, check))

    def test_later_only_closes(self):
        choice = self.open(greeting.Account.SIGNED_OUT, lambda dialog: self.button(dialog, "Later").click())
        self.assertIs(greeting.Choice.DONE, choice)

    def test_signed_in_players_only_get_lets_study(self):
        def check(dialog):
            self.assertEqual(["Let’s study"], self.buttons(dialog))
            self.button(dialog, "Let’s study").click()

        self.assertIs(greeting.Choice.DONE, self.open(greeting.Account.SIGNED_IN, check))

    def test_closing_the_window_counts_as_done(self):
        choice = self.open(greeting.Account.SIGNED_OUT, lambda dialog: dialog.close())
        self.assertIs(greeting.Choice.DONE, choice)

    def test_text_wraps_inside_the_window(self):
        def check(dialog):
            labels = [label for label in dialog.findChildren(QLabel) if label.text()]
            self.assertTrue(all(label.wordWrap() for label in labels))
            self.assertTrue(all(label.textFormat() is Qt.TextFormat.PlainText for label in labels))
            dialog.reject()

        self.open(greeting.Account.SIGNED_IN, check)


if __name__ == "__main__":
    unittest.main()
