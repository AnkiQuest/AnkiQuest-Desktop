"""Signing out drops account data without losing the upload checkpoint."""

import time
from unittest.mock import Mock

from test_addon_uploads import HeldTasks as _HeldTasks


class SignOut(_HeldTasks):
    def setUp(self):
        super().setUp()
        self.addon.client = self.current_client
        self.addon.refresh_shared_decks = Mock()
        self.addon.poll = Mock()
        self.home.sync_goal = Mock()
        self.now = int(time.time() * 1000)
        self.profile = self.mw.pm.profile
        self.checkpoint = self.addon._upload_prefs(self.api)
        self.checkpoint.update(through=self.now - 1000, shared={5: ["friend"]})

    def current_client(self):
        if not self.settings.get("token"):
            return self.addon.Client("", "", "")
        self.api.token = self.settings["token"]
        return self.api

    def sign_out(self):
        self.addon.ui.settings_dialog = Mock(return_value={"url": "", "user": "", "token": ""})
        self.addon.open_settings()

    def test_sign_out_clears_the_inbox_and_display_caches(self):
        self.addon.state["inbox"] = [{"id": 4, "body": "Private message"}]
        self.profile[self.addon.INBOX_KEY] = 4
        self.profile[self.home.PLAN_KEY] = {"target": 42}
        self.home.local["board"] = [{"user": "hill"}]
        for key in ("board_request", "board_retry", "goal_request"):
            self.home.local[key] = object()

        self.sign_out()

        self.assertEqual("", self.settings["token"])
        self.assertEqual("", self.settings["user"])
        self.assertEqual([], self.addon.state["inbox"])
        self.assertNotIn(self.addon.INBOX_KEY, self.profile)
        self.assertNotIn(self.home.PLAN_KEY, self.profile)
        self.assertIsNone(self.home.local["board"])
        for key in ("board_request", "board_retry", "goal_request"):
            self.assertIsNone(self.home.local[key])
        self.assertNotIn("shared", self.checkpoint)
        self.assertEqual(self.now - 1000, self.checkpoint["through"])

    def test_returning_to_the_same_account_uploads_only_new_reviews(self):
        old_review, new_review = self.now - 2000, self.now
        self.checkpoint["recent"] = [old_review]
        self.db.executemany(
            "insert into revlog values (?, 1, 3, 1, 5000, 1, 3)",
            [(old_review,), (new_review,)],
        )
        self.sign_out()
        self.addon.sync_settings = Mock()

        self.addon._finish_sign_in({"url": self.api.base, "user": self.api.name, "token": "new-token"})
        self.finish()

        uploaded = self.api.upload.call_args.args[0]
        self.assertEqual([new_review], [review["id"] for review in uploaded])

    def test_sign_out_invalidates_an_upload_that_has_not_started(self):
        self.db.execute("insert into revlog values (?, 1, 3, 1, 5000, 1, 3)", (self.now,))
        self.addon.refresh(False)
        self.assertEqual(1, len(self.tasks))

        self.sign_out()
        self.finish()

        self.api.upload.assert_not_called()


class PrivateCountdowns(_HeldTasks):
    """Countdowns belong to the account they were saved on, not to the computer."""

    EXAM = [{"name": "Spanish exam", "date": "2026-12-01", "deck": None}]

    def setUp(self):
        super().setUp()
        self.addon.refresh_shared_decks = Mock()
        self.addon.poll = Mock()
        self.home.sync_goal = Mock()
        self.addon.client = lambda: self.addon.Client(
            self.settings.get("url", ""), self.settings.get("user", ""), self.settings.get("token", "")
        )
        self.synced = []
        self.addon.sync_settings = lambda: self.synced.append(dict(self.settings))
        self.settings["countdowns"] = self.EXAM
        self.settings[self.addon.settings_sync.CHANGED_KEY] = {"countdowns": 7}

    def switch(self, user, token):
        self.addon._save_account_config({"url": "https://example.test" if user else "", "user": user, "token": token})

    def countdowns(self):
        return self.settings["countdowns"], self.settings[self.addon.settings_sync.CHANGED_KEY]["countdowns"]

    def test_another_account_starts_without_the_first_accounts_countdowns(self):
        self.switch("second", "second-token")

        # The sync for the new account sees no list, so it sends nothing of the first's.
        self.assertEqual(([], 0), self.countdowns())
        self.assertEqual([], self.synced[-1]["countdowns"])

    def test_returning_brings_each_accounts_countdowns_back(self):
        self.switch("second", "second-token")
        driving = [{"name": "Driving test", "date": "2027-01-10", "deck": None}]
        self.settings["countdowns"] = driving
        self.settings[self.addon.settings_sync.CHANGED_KEY]["countdowns"] = 9

        self.switch("hill", "secret")
        self.assertEqual((self.EXAM, 7), self.countdowns())
        self.switch("second", "second-token")
        self.assertEqual((driving, 9), self.countdowns())

    def test_signing_out_and_back_in_keeps_the_countdowns(self):
        self.switch("", "")
        self.assertEqual(([], 0), self.countdowns())

        self.switch("hill", "new-token")
        self.assertEqual((self.EXAM, 7), self.countdowns())

    def test_a_new_token_for_the_same_account_keeps_its_countdowns(self):
        self.switch("hill", "new-token")
        self.assertEqual((self.EXAM, 7), self.countdowns())
