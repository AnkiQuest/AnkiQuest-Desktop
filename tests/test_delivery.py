"""The announcement queue's own rules: account records, quiet hours and which inbox rows may alert."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from addon_loader import load_in_package

delivery = load_in_package("ankiquest_delivery_test", "delivery")


def account(user="hill", base="https://ankiquest.example"):
    return SimpleNamespace(base=base, user=user)


def reminder(kind, now=None, **extra):
    entry = dict(kind=kind, **extra)
    if now is not None:
        entry["created_at"] = now
    return entry


class Records(unittest.TestCase):
    def test_the_first_account_inherits_the_pre_upgrade_profile(self):
        profile = {
            "ankiquestInboxCursor": 42,
            "ankiquestSeenDeckCopies": ["old"],
            "ankiquestStreakDay": "2026-01-01",
        }
        record = delivery._record(profile, account())
        self.assertEqual(42, record["cursor"])
        self.assertEqual(["old"], record["copies"])
        self.assertEqual("2026-01-01", record["warned"])
        self.assertIs(record, delivery._record(profile, account()))
        self.assertEqual([], profile.setdefault("x", []))

    def test_a_second_account_starts_from_nothing(self):
        profile = {"ankiquestInboxCursor": 42, "ankiquestSeenDeckCopies": ["old"], "ankiquestStreakDay": "2026-01-01"}
        delivery._record(profile, account())
        second = delivery._record(profile, account("other"))
        self.assertEqual((0, [], None), (second["cursor"], second["copies"], second["warned"]))
        # An account's record is remembered, and another base is another account.
        self.assertIs(second, delivery._record(profile, account("other")))
        self.assertIsNot(second, delivery._record(profile, account("other", "https://elsewhere.example")))


class Fetching(unittest.TestCase):
    def test_pages_are_followed_back_until_the_cursor(self):
        pages = [
            SimpleNamespace(items=[dict(id=3)], before=1),
            SimpleNamespace(items=[dict(id=2), dict(id=1)], before=None),
        ]

        def load(api, before=None):
            return pages.pop(0)

        with patch.object(delivery.activity, "_load", side_effect=load):
            page, rows = delivery._fetch(account(), 0)
        self.assertEqual([3, 2, 1], [row["id"] for row in rows])
        self.assertEqual(1, page.before)

    def test_pagination_that_does_not_advance_is_refused(self):
        pages = [SimpleNamespace(items=[], before=5), SimpleNamespace(items=[], before=5)]
        with patch.object(delivery.activity, "_load", side_effect=lambda api, before=None: pages.pop(0)):
            with self.assertRaises(ValueError):
                delivery._fetch(account(), 0)


class DeviceHours(unittest.TestCase):
    def test_the_hour_follows_the_player_s_clock(self):
        # 3600s after midnight on UTC has the device at hour 1; an offset west of UTC pushes it back.
        hour = 3600
        self.assertEqual(1, delivery._device_hour(hour, 0))
        self.assertEqual(0, delivery._device_hour(hour, 60))
        self.assertEqual(23, delivery._device_hour(hour, 90))
        # An offset of a whole day keeps the hour: only the time within the day matters.
        self.assertEqual(1, delivery._device_hour(hour, 24 * 60))


class QuietHours(unittest.TestCase):
    def test_equal_ends_switch_quiet_hours_off(self):
        self.assertFalse(delivery._quiet({"quiet_start": 8, "quiet_end": 8}, 3))

    def test_an_unknown_hour_holds(self):
        settings = {"quiet_start": 22, "quiet_end": 6}
        self.assertTrue(delivery._quiet(settings, None))
        self.assertTrue(delivery._quiet(settings, 23))
        self.assertTrue(delivery._quiet(settings, 0))
        self.assertFalse(delivery._quiet(settings, 22 - 1))

    def test_a_range_within_one_day_holds_inside_it(self):
        settings = {"quiet_start": 12, "quiet_end": 14}
        self.assertTrue(delivery._quiet(settings, 13))
        self.assertFalse(delivery._quiet(settings, 14))
        self.assertFalse(delivery._quiet(settings, 12 - 1))


class Eligibility(unittest.TestCase):
    DAY_ENDS_AT = 1000 * 3600
    NOW = DAY_ENDS_AT // 1000 - 600

    def profile(self, **extra):
        settings = dict(day_ends_at=self.DAY_ENDS_AT, _day_status="pending", streak_warning=False)
        settings.update(extra)
        return settings

    def test_rows_that_speak_for_themselves_never_alert(self):
        for entry in ({"kind": "reminder_daily", "quiet": True}, {"kind": "celebration", "read_at": True}):
            self.assertFalse(delivery._eligible(entry, self.NOW, self.profile(), {}))
        # A win of the player's own is for the inbox alone.
        self.assertFalse(delivery._eligible({"kind": "celebration", "id": 7}, self.NOW, self.profile(), {}))
        # Any other kind may alert.
        self.assertTrue(delivery._eligible({"kind": "friend_goal"}, self.NOW, self.profile(), {}))

    def test_reminders_only_alert_while_their_setting_is_on_and_they_are_fresh(self):
        fresh = reminder("reminder_milestone", self.NOW - 100)
        self.assertTrue(delivery._eligible(fresh, self.NOW, self.profile(), {"milestone": True}))
        self.assertFalse(delivery._eligible(fresh, self.NOW, self.profile(), {"milestone": False}))
        old = reminder("reminder_milestone", self.NOW - delivery._REMINDER_AGE - 1)
        self.assertFalse(delivery._eligible(old, self.NOW, self.profile(), {"milestone": True}))

    def test_the_daily_reminder_needs_the_day_still_to_decide(self):
        reminders = {"gentle_daily": True}
        fresh = reminder("reminder_daily", self.NOW - 100)
        self.assertTrue(delivery._eligible(fresh, self.NOW, self.profile(), reminders))
        # Yesterday's reminder, from a day that has ended, never alerts.
        self.assertFalse(delivery._eligible(reminder("reminder_daily", created_at=self.NOW + 100), self.NOW, self.profile(), reminders))
        # A day that already counts, or a warning already heard, stays quiet.
        self.assertFalse(delivery._eligible(fresh, self.NOW, self.profile(_day_status="met"), reminders))

    def test_the_urgent_reminder_needs_a_streak_to_warn_about(self):
        reminders = {"urgent_streak": True}
        fresh = reminder("reminder_urgent", self.NOW - 100)
        self.assertTrue(delivery._eligible(fresh, self.NOW, self.profile(streak_warning=True), reminders))
        self.assertFalse(delivery._eligible(fresh, self.NOW, self.profile(), reminders))
        # Outside today's window the urgent reminder stays quiet too.
        self.assertFalse(delivery._eligible(reminder("reminder_urgent", created_at=self.NOW + 100), self.NOW, self.profile(streak_warning=True), reminders))

    def test_windowed_reminders_alert_within_the_day_only(self):
        reminders = {"freeze_refill": True}
        fresh = reminder("reminder_freeze_refill", self.NOW - 100)
        old = reminder("reminder_freeze_refill", self.DAY_ENDS_AT - delivery.notify.FRESH_SECONDS - 1)
        self.assertTrue(delivery._eligible(fresh, self.NOW, self.profile(), reminders))
        self.assertFalse(delivery._eligible(old, self.NOW, self.profile(), reminders))


if __name__ == "__main__":
    unittest.main()
