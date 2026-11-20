"""The add-on's verdict on today agrees with the server's golden cases."""

import json
import unittest
from pathlib import Path

from addon_loader import load_module

day_verdict = load_module("aq_day_verdict", "day_verdict.py")

# The Server copy (tests/server-fixtures/README.md), with the observed study cases of Server #80;
# tests/fixtures holds the server code's older one.
FIXTURE = Path(__file__).resolve().parent / "server-fixtures" / "day_verdicts.json"


class DayVerdicts(unittest.TestCase):
    def test_every_server_case(self):
        cases = json.loads(FIXTURE.read_text("utf-8"))["cases"]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["name"]):
                found = day_verdict.verdict(case["server"], case["pending"], case["now_ms"])
                expected = case["expected"]
                if expected is None:
                    self.assertIsNone(found)
                    continue
                waiting = found.pop("waiting")
                # Copies from before the server pinned the day's words have no label.
                if "label" in expected:
                    expected = dict(expected)
                    self.assertEqual(expected.pop("label"), day_verdict.label(found))
                self.assertEqual(expected, found)
                # Waiting: today counts, but the server says so only once the unsent reviews arrive.
                self.assertEqual(expected["met"] and expected["streak_state"] != case["server"]["streak_state"], waiting)

    def test_the_cases_include_observed_answers(self):
        # Pending observed answers (AnkiQuest Lite) have no time_ms; their day is unverified.
        cases = json.loads(FIXTURE.read_text("utf-8"))["cases"]
        self.assertTrue(any("time_ms" not in review for case in cases for review in case["pending"]))
        self.assertIn("unverified", {(case["expected"] or {}).get("label") for case in cases})

    def test_a_profile_without_day_bounds_has_no_verdict(self):
        # Servers older than the add-on leave out today's starts_at and time_ms.
        server = {
            "streak": 3, "streak_state": "pending", "day_ends_at": 2_000, "last_review_id": 100,
            "today": {"reviews": 1, "minutes": 4, "streak_minutes": 5, "starts_at": 0, "time_ms": 240_000},
        }
        self.assertIsNotNone(day_verdict.verdict(server, [], 1_000))
        for missing in ("starts_at", "time_ms"):
            today = {key: value for key, value in server["today"].items() if key != missing}
            self.assertIsNone(day_verdict.verdict(dict(server, today=today), [], 1_000), missing)

    def test_a_review_on_a_protected_day_is_not_protected(self):
        # The freeze kept yesterday; with a review today the day reads short, not unstudied.
        server = {
            "streak": 4, "streak_state": "protected", "day_ends_at": 2_000, "last_review_id": 10,
            "today": {"starts_at": 100, "reviews": 1, "time_ms": 180_000, "minutes": 3, "streak_minutes": 10},
        }
        shown = day_verdict._for_display(server, day_verdict.verdict(server, [], 1_000))
        self.assertEqual("pending", shown["_day_status"])
        self.assertEqual("short", day_verdict.label(day_verdict.verdict(server, [], 1_000)))
        untouched = dict(server, today=dict(server["today"], reviews=0, time_ms=0, minutes=0))
        self.assertEqual("protected", day_verdict._for_display(untouched, day_verdict.verdict(untouched, [], 1_000))["_day_status"])

    def test_no_profile_says_nothing(self):
        self.assertIsNone(day_verdict.verdict(None, [], 1_000))

    def test_unsent_reads_what_the_uploader_sends(self):
        seen = []

        class Db:
            def all(self, sql, *args):
                seen.append((sql, args))
                return [(7, 1200), (8, None)]

        class Col:
            db = Db()

        self.assertEqual([{"id": 7, "time_ms": 1200}, {"id": 8, "time_ms": 0}], day_verdict.unsent(Col(), {"last_review_id": 5}))
        self.assertIn("ease > 0 and type < 4", seen[0][0])
        self.assertEqual((5,), seen[0][1])
        self.assertEqual([], day_verdict.unsent(Col(), {}))


if __name__ == "__main__":
    unittest.main()
