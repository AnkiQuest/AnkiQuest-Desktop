"""Aki's greeting on the first profile open: once per computer, after Anki's own dialogs."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_deck_completion as addon_fixture


class GreetingDialog(unittest.TestCase):
    def test_the_dialog_with_real_qt(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("qt_greeting.py"))],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class GreetingFlow(unittest.TestCase):
    run_task = addon_fixture.RefreshTests.run_task
    read_rows = addon_fixture.RefreshTests.read_rows
    write_config = addon_fixture.RefreshTests.write_config

    def setUp(self):
        addon_fixture.RefreshTests.setUp(self)
        self.greeting = self.addon.greeting
        self.mw.pm.meta = {}
        self.modal = None
        self.choice = self.greeting.Choice.DONE
        self.asked = []
        self.events = []

        # Timers run at once; the dialogs answer as the test says.
        self.addon.QTimer = SimpleNamespace(singleShot=lambda _ms, run: run())
        self.addon.QApplication = SimpleNamespace(activeModalWidget=lambda: self.modal)
        self.greeting.ask = self.ask
        self.addon.ask_account = Mock(return_value=None)
        self.addon._finish_sign_in = Mock()
        self.addon._moments = SimpleNamespace(
            _hold=lambda: self.events.append("hold"), _release=lambda: self.events.append("release"),
        )
        self.sign_out()

    def ask(self, parent, account):
        self.events.append("greeting")
        self.asked.append(account)
        return self.choice

    def sign_out(self):
        self.api.configured = False
        self.settings = {"url": "", "user": "", "token": ""}

    def sign_in(self):
        self.api.configured = True
        self.settings = {"url": "https://example.test", "user": "cerro", "token": "secret"}

    def stored(self):
        return self.greeting.state(self.mw.pm.meta)

    def test_a_computer_without_a_stored_state_owes_the_greeting(self):
        self.assertIs(self.greeting.State.PENDING, self.greeting.state({}))
        self.assertIs(self.greeting.State.PENDING, self.greeting.state({self.greeting.KEY: "unknown"}))
        meta = {}
        self.greeting.remember(meta, self.greeting.State.SHOWN)
        self.assertIs(self.greeting.State.SHOWN, self.greeting.state(meta))

    def test_the_first_open_greets_once(self):
        self.addon._welcome()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)
        self.assertIs(self.greeting.State.SHOWN, self.stored())

        # Another profile on the same computer is not greeted again.
        self.mw.pm.profile = {}
        self.addon._welcome()
        self.assertEqual(1, len(self.asked))

    def test_signed_out_the_greeting_is_the_sign_in_offer(self):
        self.addon._welcome()
        self.addon.ask_account.assert_not_called()
        self.assertTrue(self.mw.pm.profile[self.addon.SIGN_IN_OFFER_KEY])

        # Later means later: the same profile is not asked again on its next open.
        self.addon._welcome()
        self.addon.ask_account.assert_not_called()

    def test_sign_in_opens_the_account_dialog(self):
        self.choice = self.greeting.Choice.SIGN_IN
        answer = {"url": "https://example.test", "user": "cerro", "token": "new"}
        self.addon.ask_account.return_value = answer
        self.addon._welcome()
        self.addon.ask_account.assert_called_once_with("")
        self.addon._finish_sign_in.assert_called_once_with(answer)

    def test_signed_in_players_are_only_sent_to_study(self):
        self.sign_in()
        self.addon._welcome()
        self.assertEqual([self.greeting.Account.SIGNED_IN], self.asked)
        self.addon.ask_account.assert_not_called()

    def test_ankis_own_dialogs_go_first(self):
        self.modal = object()
        self.addon._welcome()
        self.assertEqual([], self.asked)
        self.addon.ask_account.assert_not_called()
        self.assertIs(self.greeting.State.PENDING, self.stored())

        # The next profile open finds the screen free.
        self.modal = None
        self.addon._welcome()
        self.assertEqual(1, len(self.asked))

    def test_a_review_in_progress_keeps_it_pending(self):
        self.mw.state = "review"
        self.addon._welcome()
        self.assertEqual([], self.asked)
        self.assertIs(self.greeting.State.PENDING, self.stored())

    def test_after_the_greeting_new_profiles_get_the_sign_in_offer(self):
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.addon._welcome()
        self.assertEqual([], self.asked)
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

    def test_moments_wait_until_the_greeting_closes(self):
        self.sign_in()
        self.addon._welcome()
        self.assertEqual(["hold", "greeting", "release"], self.events)


if __name__ == "__main__":
    unittest.main()
