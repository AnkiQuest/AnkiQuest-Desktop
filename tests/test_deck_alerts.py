"""A received deck alert changes one sender against the latest preferences."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from addon_loader import load_in_package

prefs = load_in_package("deck_alerts", "preferences")


class DeckAlerts(unittest.TestCase):
    def setUp(self):
        self.fresh = {
            "enabled": False, "senders": [{"user": "ana"}, {"user": "cerro"}],
            "sharing_senders": ["ana", "cerro"], "unsubscribed_senders": ["other"],
            "muted_senders": ["legacy"],
        }
        self.sent = []
        self.owned = True
        self.api = SimpleNamespace(user="hill", _request=self.request)

    def request(self, path, body=None):
        self.sent.append((path, deepcopy(body)))
        if body is not None:
            self.fresh.update(body)
        return deepcopy(self.fresh)

    def change(self, mode):
        return prefs._change_alert(self.api, "ana", mode, lambda: self.owned)

    def test_stop_and_fresh_undo(self):
        self.assertIs(prefs._AlertResult.CHANGED, self.change(prefs._AlertChange.STOP))
        self.assertEqual(("/api/deck-subscriptions/hill", {
            "enabled": False, "unsubscribed_senders": ["ana", "legacy", "other"],
        }), self.sent[-1])
        self.fresh.update(enabled=True)
        self.fresh["unsubscribed_senders"].append("remote")
        self.assertIs(prefs._AlertResult.CHANGED, self.change(prefs._AlertChange.RESTORE))
        self.assertEqual({"enabled": True, "unsubscribed_senders": ["legacy", "other", "remote"]}, self.sent[-1][1])

    def test_no_new_subscription(self):
        for updates, expected in (({"unsubscribed_senders": ["ana"]}, prefs._AlertResult.UNCHANGED),
                                  ({"sharing_senders": []}, prefs._AlertResult.UNAVAILABLE)):
            with self.subTest(updates=updates):
                self.fresh.update(unsubscribed_senders=[], sharing_senders=["ana"])
                self.fresh.update(updates)
                self.sent.clear()
                self.assertIs(expected, self.change(prefs._AlertChange.STOP))
                self.assertEqual(1, len(self.sent))
                self.assertIsNone(self.sent[0][1])

    def test_stale_queued_work(self):
        self.owned = False
        self.assertIs(prefs._AlertResult.STALE, self.change(prefs._AlertChange.STOP))
        self.assertEqual([], self.sent)

    def test_stale_after_read(self):
        def read(path, body=None):
            self.owned = False
            return self.request(path, body)
        self.api._request = read
        self.assertIs(prefs._AlertResult.STALE, self.change(prefs._AlertChange.STOP))
        self.assertEqual(1, len(self.sent))

    def test_missing_global_choice(self):
        del self.fresh["enabled"]
        with self.assertRaises(ValueError):
            self.change(prefs._AlertChange.STOP)
        self.assertEqual(1, len(self.sent))

    def test_failed_read_or_save(self):
        self.api._request = Mock(side_effect=OSError("offline"))
        with self.assertRaises(OSError):
            self.change(prefs._AlertChange.STOP)
        self.api._request = Mock(side_effect=[self.fresh, OSError("offline")])
        with self.assertRaises(OSError):
            self.change(prefs._AlertChange.STOP)


if __name__ == "__main__":
    unittest.main()
