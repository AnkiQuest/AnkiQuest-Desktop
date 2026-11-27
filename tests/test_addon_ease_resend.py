"""The one resend of the whole review history with the answer button, for a server that stores it."""

import time
import unittest
from unittest.mock import Mock, patch

from addon_loader import load_in_package
from test_addon_uploads import HeldTasks

ease_resend = load_in_package("ankiquest_ease_resend", "ease_resend")
Resend, Check = ease_resend.Resend, ease_resend.Check

DAY_MS = 86_400_000


class Transitions(unittest.TestCase):
    def test_an_account_without_a_stored_state_owes_the_resend(self):
        self.assertIs(Resend.PENDING, ease_resend.load({}))
        self.assertIs(Resend.PENDING, ease_resend.load({ease_resend.KEY: "unknown"}))

    def test_an_interrupted_resend_is_owed_again(self):
        self.assertIs(Resend.PENDING, ease_resend.load({ease_resend.KEY: Resend.SENDING.value}))

    def test_stored_states_round_trip(self):
        for resend in (Resend.NOT_NEEDED, Resend.PENDING, Resend.DONE):
            saved = {}
            ease_resend.save(saved, resend)
            self.assertIs(resend, ease_resend.load(saved))

    def test_start_moves_only_an_owed_resend_to_sending(self):
        self.assertIs(Resend.SENDING, ease_resend.start(Resend.PENDING))
        for resend in (Resend.NOT_NEEDED, Resend.SENDING, Resend.DONE):
            self.assertIs(resend, ease_resend.start(resend))

    def test_finish_records_what_the_upload_found(self):
        self.assertIs(Resend.DONE, ease_resend.finish(Resend.SENDING, Check.RESENT))
        self.assertIs(Resend.NOT_NEEDED, ease_resend.finish(Resend.SENDING, Check.COVERED))
        self.assertIs(Resend.PENDING, ease_resend.finish(Resend.SENDING, Check.UNSUPPORTED))
        self.assertIs(Resend.PENDING, ease_resend.finish(Resend.SENDING, Check.FAILED))

    def test_finish_leaves_other_states_alone(self):
        for resend in (Resend.NOT_NEEDED, Resend.PENDING, Resend.DONE):
            for check in Check:
                self.assertIs(resend, ease_resend.finish(resend, check))

    def test_a_failed_upload_owes_the_resend_again(self):
        self.assertIs(Resend.PENDING, ease_resend.fail(Resend.SENDING))
        for resend in (Resend.NOT_NEEDED, Resend.PENDING, Resend.DONE):
            self.assertIs(resend, ease_resend.fail(resend))

    def test_the_history_goes_in_batches_within_the_server_limit(self):
        rows = [(i,) for i in range(1, 12)]
        sent = []

        def read(after):
            return [row for row in rows if row[0] > after][:5]

        with patch.object(ease_resend, "MAX_PENDING", 5):
            count = ease_resend.send_history(read, sent.append)

        self.assertEqual(11, count)
        self.assertEqual([5, 5, 1], [len(batch) for batch in sent])
        self.assertEqual(rows, [row for batch in sent for row in batch])

    def test_an_empty_history_sends_nothing(self):
        send = Mock()
        self.assertEqual(0, ease_resend.send_history(lambda after: [], send))
        send.assert_not_called()


class ResendOnce(HeldTasks):
    """An account that uploaded before the add-on sent the button, on a server that now stores it."""

    def setUp(self):
        super().setUp()
        self.now = int(time.time() * 1000)
        self.old = self.now - 30 * DAY_MS
        profile = self.mw.pm.profile
        profile[self.addon.MARK_KEY] = self.now
        profile[self.addon.BASELINE_KEY] = [self.api.base, self.api.user]
        self.db.executemany(
            "insert into revlog values (?, 1, ?, 1, 5000, 1, 3)", ((self.old, 1), (self.now, 3))
        )
        self.features = {ease_resend.FEATURE}
        self.api.server_info = Mock(side_effect=lambda: (frozenset(self.features), None))
        self.set_capabilities()

    def set_capabilities(self):
        """The answer /api/capabilities gave when the profile opened: the cache the resend reads."""
        self.home.local["capabilities"] = (self.api.base, frozenset(self.features))

    def add_new_review(self):
        self.db.execute("insert into revlog values (?, 1, 3, 1, 5000, 1, 3)", (self.now + 1,))

    def state(self):
        return ease_resend.load(self.addon._upload_prefs(self.api))

    def resends(self):
        """The uploads that sent the old review again: only the history resend reaches back that far."""
        return [call for call in self.api.upload.call_args_list if self.old in [r["id"] for r in call.args[0]]]

    def test_a_server_that_stores_the_button_gets_the_whole_history_once(self):
        self.addon.refresh(False, resync=True)
        self.finish()

        resends = self.resends()
        self.assertEqual(1, len(resends))
        reviews, _, silent = resends[0].args[:3]
        self.assertEqual([1, 3], [row["ease"] for row in reviews])
        self.assertTrue(silent, "a resend announces nothing")
        self.assertIs(Resend.DONE, self.state())
        self.assertEqual(self.now, self.addon._upload_prefs(self.api)["through"], "the mark stays")

        self.addon.refresh(False, resync=True)
        self.finish()
        self.assertEqual(1, len(self.resends()), "the history is not sent a second time")

    def test_a_server_without_the_button_waits_until_it_stores_it(self):
        self.features = set()
        self.set_capabilities()
        self.addon.refresh(False, resync=True)
        self.finish()

        self.assertEqual([], self.resends())
        self.assertIs(Resend.PENDING, self.state())

        self.features = {ease_resend.FEATURE}
        self.set_capabilities()
        self.addon.refresh(False, resync=True)
        self.finish()
        self.assertEqual(1, len(self.resends()))
        self.assertIs(Resend.DONE, self.state())

    def test_an_empty_cache_keeps_the_resend_owed_and_makes_no_request(self):
        # The cache is empty: the profile has not learned the server's features yet. The resend
        # must not spend itself on that, and must not ask the server here.
        self.home.local["capabilities"] = None
        self.addon.refresh(False, resync=True)
        self.finish()

        self.assertEqual([], self.resends())
        self.assertIs(Resend.PENDING, self.state())
        self.api.server_info.assert_not_called()

        # The profile opens and learns them; the next upload resends.
        self.set_capabilities()
        self.addon.refresh(False, resync=True)
        self.finish()
        self.assertEqual(1, len(self.resends()))
        self.assertIs(Resend.DONE, self.state())

    def test_an_upload_after_each_answer_does_not_ask_the_server(self):
        self.addon.refresh(False)
        self.finish()

        self.api.server_info.assert_not_called()
        self.assertIs(Resend.PENDING, self.state())

    def test_a_failed_resend_is_tried_again_and_keeps_the_upload(self):
        self.add_new_review()
        self.api.upload.side_effect = [{}, OSError("offline")]
        self.addon.refresh(False, resync=True)
        self.finish()
        self.assertIs(Resend.PENDING, self.state())
        self.assertEqual(self.now + 1, self.addon._upload_prefs(self.api)["through"], "the upload counts")

        self.api.upload.side_effect = None
        self.addon.refresh(False, resync=True)
        self.finish()
        self.assertIs(Resend.DONE, self.state())

    def test_a_whole_history_upload_already_carries_the_button(self):
        self.addon.upload_everything()
        self.finish()

        self.assertEqual(1, len(self.resends()), "the history upload is the only pass")
        self.assertIs(Resend.NOT_NEEDED, self.state())


if __name__ == "__main__":
    unittest.main()
