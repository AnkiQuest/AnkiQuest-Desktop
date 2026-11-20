"""The poll's wiring for the token-only password card; run with python -m unittest discover -s tests."""

import unittest
from unittest.mock import Mock, patch

from test_addon_uploads import HeldTasks, today


class PasswordPoll(HeldTasks):
    def setUp(self):
        super().setUp()
        # Deck copies and settings sync poll on their own; only the board's poll is under test.
        self.addon.copies_ui.poll = Mock()
        self.addon._poll_settings = Mock()
        self.api.sign_in_methods = Mock(return_value={"sign_in": "token_only"})
        self.api.set_password = Mock(return_value={})
        self.account = [self.api.base, self.api.user, self.api.token]

    def end(self, index):
        """Ends one held task, as Anki would on its main thread."""
        work, done = self.tasks.pop(index)
        future = today.Future()
        future.set_result(work())
        done(future)

    def save(self):
        """Saves a password through the form, its request answered at once."""
        def dialog(_parent, submit):
            finished = []
            submit("a new long password", finished.append)
            self.end(-1)
            return finished == [None]

        with patch.object(self.addon.password_ui, "password_dialog", dialog):
            self.addon.set_password()

    def test_a_token_only_player_is_offered_the_card(self):
        self.addon.poll(quiet=True)
        self.end(0)
        self.assertEqual(self.account, self.addon.state["password_prompt"])

    def test_a_player_with_a_password_is_not_offered_it(self):
        self.api.sign_in_methods.return_value = {"sign_in": "password"}
        self.addon.poll(quiet=True)
        self.end(0)
        self.assertIsNone(self.addon.state["password_prompt"])

    def test_a_failed_sign_in_request_does_not_fail_the_poll(self):
        self.api.sign_in_methods.side_effect = OSError("offline")
        self.addon.state["profile"] = None
        self.addon.poll(quiet=True)
        self.end(0)
        self.assertIsNone(self.addon.state["password_prompt"])
        self.assertEqual(2, self.addon.state["profile"]["level"])

    def test_not_now_keeps_the_server_from_being_asked(self):
        self.addon.password_later()
        self.addon.poll(quiet=True)
        self.end(0)
        self.api.sign_in_methods.assert_not_called()
        self.assertIsNone(self.addon.state["password_prompt"])

    def test_not_now_during_a_poll_is_kept(self):
        self.addon.poll(quiet=True)
        self.addon.password_later()
        self.end(0)
        self.assertIsNone(self.addon.state["password_prompt"], "the card stays hidden")

    def test_a_password_saved_during_a_poll_is_kept(self):
        self.addon.poll(quiet=True)
        self.save()
        self.api.set_password.assert_called_once_with("a new long password")
        self.end(0)
        self.assertIsNone(self.addon.state["password_prompt"], "the card stays gone")

    def test_the_next_poll_offers_the_card_again_when_still_token_only(self):
        self.addon.poll(quiet=True)
        self.save()
        self.end(0)
        self.addon.poll(quiet=True)
        self.end(0)
        self.assertEqual(self.account, self.addon.state["password_prompt"])


if __name__ == "__main__":
    unittest.main()
