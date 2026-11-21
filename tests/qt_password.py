"""The token-only player's password form with real Qt: validation, refusal, retry, cancellation."""
import unittest
from unittest.mock import patch

from aqt.qt import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QWidget
from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
ui = load_in_package("password_qt", "password_ui")

PASSWORD = "a new long password"


class PasswordForm(unittest.TestCase):
    def setUp(self):
        self.parent = QWidget()
        self.sent = []
        # What the server answers each submit with: None for saved, or its error.
        self.answers = []

    def tearDown(self):
        self.parent.close()
        app.processEvents()

    def submit(self, password, finish):
        self.sent.append(password)
        finish(self.answers.pop(0))

    def run_form(self, inspect):
        """Runs the form with `inspect(dialog)` in place of the player; whether it was saved."""
        def player(dialog):
            dialog.show()
            inspect(dialog)
            return dialog.result()

        with patch.object(QDialog, "exec", player):
            return ui.password_dialog(self.parent, self.submit)

    @staticmethod
    def fill(dialog, password, repeat):
        first, second = dialog.findChildren(QLineEdit)
        first.setText(password)
        second.setText(repeat)

    @staticmethod
    def button(dialog, text):
        return next(button for button in dialog.findChildren(QPushButton) if button.text() == text)

    @staticmethod
    def status(dialog):
        return dialog.findChild(QLabel).text()

    def test_the_form_is_worded_as_the_app(self):
        def inspect(dialog):
            self.assertEqual("Set a password", dialog.windowTitle())
            self.assertEqual(["New password", "New password again"],
                             [field.placeholderText() for field in dialog.findChildren(QLineEdit)])
            self.assertTrue(all(field.echoMode() == QLineEdit.EchoMode.Password for field in dialog.findChildren(QLineEdit)))
            self.assertTrue(self.button(dialog, "Save").isDefault())
            self.button(dialog, "Cancel").click()

        self.assertFalse(self.run_form(inspect))

    def test_a_short_or_mismatched_password_is_not_sent(self):
        def inspect(dialog):
            self.fill(dialog, "short", "short")
            self.button(dialog, "Save").click()
            self.assertEqual("Use 10 to 256 characters.", self.status(dialog))
            self.fill(dialog, PASSWORD, PASSWORD + "!")
            self.button(dialog, "Save").click()
            self.assertEqual("The two passwords are not the same.", self.status(dialog))
            self.assertTrue(dialog.isVisible(), "the form stays open")
            self.button(dialog, "Cancel").click()

        self.assertFalse(self.run_form(inspect))
        self.assertEqual([], self.sent)

    def test_a_refused_password_can_be_retried(self):
        self.answers = ["Password is too common.", None]

        def inspect(dialog):
            self.fill(dialog, PASSWORD, PASSWORD)
            self.button(dialog, "Save").click()
            self.assertEqual("Password is too common.", self.status(dialog))
            self.assertTrue(dialog.isVisible(), "the form stays open with the server's error")
            self.assertTrue(self.button(dialog, "Save").isEnabled())
            self.fill(dialog, PASSWORD + "s", PASSWORD + "s")
            self.button(dialog, "Save").click()

        self.assertTrue(self.run_form(inspect))
        self.assertEqual([PASSWORD, PASSWORD + "s"], self.sent)

    def test_save_waits_for_the_server(self):
        held = []
        self.submit = lambda password, finish: held.append(finish)

        def inspect(dialog):
            self.fill(dialog, PASSWORD, PASSWORD)
            self.button(dialog, "Save").click()
            self.assertFalse(self.button(dialog, "Save").isEnabled(), "one request at a time")
            self.assertEqual("Connecting…", self.status(dialog))
            held.pop()(None)

        self.assertTrue(self.run_form(inspect))

    def test_cancel_sends_nothing(self):
        def inspect(dialog):
            self.fill(dialog, PASSWORD, PASSWORD)
            self.button(dialog, "Cancel").click()

        self.assertFalse(self.run_form(inspect))
        self.assertEqual([], self.sent)


if __name__ == "__main__":
    unittest.main()
