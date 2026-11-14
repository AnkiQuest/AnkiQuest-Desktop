"""A poll belongs to the account it was started for."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from test_addon_uploads import HeldTasks


class PollAccount(HeldTasks):
    def setUp(self):
        super().setUp()
        # Deck copies and settings sync poll on their own; only the board's poll is under test.
        self.addon.copies_ui.poll = Mock()
        self.addon._poll_settings = Mock()

    def switch(self, user):
        """Signs in as `user`, as the account and settings dialogs do."""
        self.api = SimpleNamespace(**vars(self.api))
        self.api.user = self.api.name = user
        self.api.profile = Mock(return_value={"user": user})
        self.addon.state["profile"] = None

    def test_the_new_account_polls_while_the_old_one_still_does(self):
        self.addon.state["profile"] = None
        self.addon.poll(quiet=True)
        self.switch("cerro")
        self.addon.poll(quiet=True)
        self.assertEqual(2, len(self.tasks), "the new account's poll starts at once")

    def test_an_old_accounts_poll_is_dropped(self):
        self.addon.state["profile"] = None
        self.addon.poll(quiet=True)
        self.switch("cerro")
        self.finish()
        self.assertIsNone(self.addon.state["profile"], "hill's profile is not shown to cerro")

    def test_the_current_accounts_poll_lands(self):
        self.addon.state["profile"] = None
        self.addon.poll(quiet=True)
        self.addon.poll(quiet=True)
        self.assertEqual(1, len(self.tasks), "one poll per account at a time")
        self.finish()
        self.assertEqual(2, self.addon.state["profile"]["level"])


    def test_an_unlock_made_offline_is_sent_by_the_next_poll(self):
        unlock = self.addon.companion_unlock
        key = unlock.account(self.api)
        unlock.record(self.prefs(), key, "cow")
        self.api.capabilities = Mock(return_value=frozenset([unlock.FEATURE]))
        self.api.unlock = Mock(side_effect=[OSError("offline"), {"unlocks": ["cow"]}])
        self.addon.state["profile"] = None
        self.addon.poll(quiet=True)
        self.finish()
        self.assertEqual(["cow"], unlock.pending(self.prefs(), key), "kept while offline")
        self.addon.poll(quiet=True)
        self.finish()
        self.assertEqual([], unlock.pending(self.prefs(), key))
        self.assertEqual(2, self.api.unlock.call_count)

    def prefs(self):
        return self.addon.mw.pm.profile


if __name__ == "__main__":
    unittest.main()
