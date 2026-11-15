"""Aki's greeting on the first profile open: once per computer, after Anki's own dialogs."""

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_deck_completion as addon_fixture

# More rounds than any flow here queues; reaching it means a retry never stops.
DRAIN_LIMIT = 50


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

        # Timers wait in a queue until the test runs them; the dialogs answer as the test says.
        self.timers = []
        self.addon.QTimer = SimpleNamespace(singleShot=lambda ms, run: self.timers.append((ms, run)))
        self.addon.QApplication = SimpleNamespace(activeModalWidget=lambda: self.modal)
        self.greeting.ask = self.ask
        self.addon.ask_account = Mock(return_value=None)
        self.addon._finish_sign_in = Mock()
        self.addon._moments = SimpleNamespace(
            _hold=lambda: self.events.append("hold"), _release=lambda: self.events.append("release"),
            _transition=Mock(),
        )
        self.addon._delivery = SimpleNamespace(_flush=Mock())
        self.sign_out()

    def tick(self):
        """Runs the callbacks queued so far, as one turn of Qt's event loop would."""
        due, self.timers = self.timers, []
        for _ms, run in due:
            run()

    def drain(self):
        """Runs queued callbacks, and those they queue, until none are left."""
        for _ in range(DRAIN_LIMIT):
            if not self.timers:
                return
            self.tick()
        self.fail("callbacks kept queueing more")

    def open_profile(self):
        self.addon._welcome()
        self.drain()

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
        self.open_profile()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)
        self.assertIs(self.greeting.State.SHOWN, self.stored())

        # Another profile on the same computer is not greeted again.
        self.mw.pm.profile = {}
        self.open_profile()
        self.assertEqual(1, len(self.asked))

    def test_signed_out_the_greeting_is_the_sign_in_offer(self):
        self.open_profile()
        self.addon.ask_account.assert_not_called()
        self.assertTrue(self.mw.pm.profile[self.addon.SIGN_IN_OFFER_KEY])

        # Later means later: the same profile is not asked again on its next open.
        self.open_profile()
        self.addon.ask_account.assert_not_called()

    def test_sign_in_opens_the_account_dialog(self):
        self.choice = self.greeting.Choice.SIGN_IN
        answer = {"url": "https://example.test", "user": "cerro", "token": "new"}
        self.addon.ask_account.return_value = answer
        self.open_profile()
        self.addon.ask_account.assert_called_once_with("")
        self.addon._finish_sign_in.assert_called_once_with(answer)

    def test_signed_in_players_are_only_sent_to_study(self):
        self.sign_in()
        self.open_profile()
        self.assertEqual([self.greeting.Account.SIGNED_IN], self.asked)
        self.addon.ask_account.assert_not_called()

    def end_review(self):
        self.mw.state = "overview"
        self.addon.on_state_change("overview", "review")

    def test_ankis_own_dialogs_go_first(self):
        self.modal = object()
        self.addon._welcome()
        for _ in range(3):
            self.tick()
        self.assertEqual([], self.asked)
        self.addon.ask_account.assert_not_called()
        self.assertIs(self.greeting.State.PENDING, self.stored())

        # One retry at a time, not one more per check.
        self.assertEqual([self.addon.WELCOME_RETRY_MS], [ms for ms, _run in self.timers])

    def test_the_greeting_follows_ankis_dialog_without_another_open(self):
        self.addon._welcome()

        # Anki's startup dialog is in front when the greeting would show.
        self.modal = object()
        self.tick()
        self.assertEqual([], self.asked)

        # Closing it lets the greeting through; the profile is not opened again.
        self.modal = None
        self.drain()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)

    def test_a_review_in_progress_keeps_it_pending(self):
        self.mw.state = "review"
        self.open_profile()
        self.assertEqual([], self.asked)
        self.assertIs(self.greeting.State.PENDING, self.stored())

        # The end of the review lets it through.
        self.end_review()
        self.drain()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)

    def test_a_dialog_during_a_review_holds_it_until_both_end(self):
        self.mw.state = "review"
        self.modal = object()
        self.open_profile()
        self.end_review()
        self.tick()
        self.assertEqual([], self.asked)

        self.modal = None
        self.drain()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)

    def test_closing_the_profile_ends_the_wait(self):
        first = self.mw.pm.profile
        self.modal = object()
        self.addon._welcome()
        self.tick()

        # The profile closes; nothing is shown and the retries stop.
        self.addon._end_welcome()
        self.mw.pm.profile = None
        self.modal = None
        self.drain()
        self.assertEqual([], self.asked)
        self.assertIs(self.greeting.State.PENDING, self.stored())
        self.assertNotIn(self.addon.SIGN_IN_OFFER_KEY, first)

    def test_a_profile_switch_moves_the_greeting_to_the_new_profile(self):
        first = self.mw.pm.profile
        self.modal = object()
        self.addon._welcome()
        self.tick()

        # Another profile opens while the first one's greeting waits.
        self.mw.pm.profile = second = {}
        self.addon._welcome()
        self.modal = None
        self.drain()
        self.assertEqual([self.greeting.Account.SIGNED_OUT], self.asked)
        self.assertNotIn(self.addon.SIGN_IN_OFFER_KEY, first)
        self.assertTrue(second[self.addon.SIGN_IN_OFFER_KEY])

    def test_a_greeting_shown_meanwhile_is_not_shown_again(self):
        self.modal = object()
        self.addon._welcome()
        self.tick()

        # Stored as shown while this one waited: the profile gets its sign-in offer instead.
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.modal = None
        self.drain()
        self.assertEqual([], self.asked)
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

    def test_the_sign_in_offer_follows_ankis_dialog(self):
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.modal = object()
        self.addon._welcome()
        self.tick()
        self.addon.ask_account.assert_not_called()

        self.modal = None
        self.drain()
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

    def test_the_sign_in_offer_follows_a_review(self):
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.mw.state = "review"
        self.open_profile()
        self.addon.ask_account.assert_not_called()

        self.end_review()
        self.drain()
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

    def test_signing_in_while_waiting_drops_the_sign_in_offer(self):
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.modal = object()
        self.addon._welcome()
        self.tick()

        # Anki's dialog was the add-on's own settings, where the player signed in.
        self.sign_in()
        self.modal = None
        self.drain()
        self.addon.ask_account.assert_not_called()

    def test_after_the_greeting_new_profiles_get_the_sign_in_offer(self):
        self.greeting.remember(self.mw.pm.meta, self.greeting.State.SHOWN)
        self.open_profile()
        self.assertEqual([], self.asked)
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

    def test_moments_wait_until_the_greeting_closes(self):
        self.sign_in()
        self.open_profile()
        self.assertEqual(["hold", "greeting", "release"], self.events)


if __name__ == "__main__":
    unittest.main()
