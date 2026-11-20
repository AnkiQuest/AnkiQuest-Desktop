"""Observed study from AnkiQuest Lite (Server #80): unverified days and observed XP, worded as
on the website."""

import json
import unittest
from datetime import date
from pathlib import Path

from addon_loader import load_in_package

board = load_in_package("aq_observed", "board")
day_verdict = load_in_package("aq_observed", "day_verdict")
heatmap = load_in_package("aq_observed", "heatmap")
heatmap_ui = load_in_package("aq_observed", "heatmap_ui")
moods = load_in_package("aq_observed", "moods")

# The Server copy (tests/server-fixtures/README.md).
OBSERVED = json.loads((Path(__file__).parent / "server-fixtures/observed_reviews.json").read_text("utf-8"))
MINUTE_MS = 60_000


def english(text):
    return text


def merged_days():
    """Each day the server works out from exact rows, observed answers and day counts, as the
    profile's heatmap cell it sends."""
    for case in OBSERVED["merge"]:
        for day in case["expected"]["days"]:
            cell = {
                "date": day["date"], "reviews": day["reviews"], "observed": day["observed"],
                "minutes": day["time_ms"] // MINUTE_MS, "streak_minutes": case["streak_minutes"],
                "state": day["state"], "frozen": False,
            }
            yield case["name"], cell


def unverified_profile(**changes):
    """A profile whose today counts on an observed answer, short of the 10-minute minimum."""
    profile = {
        "streak": 2, "streak_state": "unverified", "day_ends_at": 2_000, "last_review_id": 10,
        "today": {"starts_at": 100, "reviews": 1, "observed": 1, "time_ms": 0, "minutes": 0, "streak_minutes": 10},
    }
    profile.update(changes)
    return profile


class MergedDays(unittest.TestCase):
    def test_the_cases_have_unverified_days(self):
        self.assertIn("unverified", {cell["state"] for _, cell in merged_days()})

    def test_each_merged_day_reads_as_the_server_judged_it(self):
        for name, cell in merged_days():
            with self.subTest(case=name, date=cell["date"]):
                day = date.fromisoformat(cell["date"])
                server = heatmap.server_days({"heatmap": [cell]})
                self.assertEqual(cell["state"], server.verdicts[day].state)

                # A met or unverified day counts toward the streak and looks studied.
                data = heatmap.summarize(day, server.reviews, {}, server.protected, server.verdicts)
                counts = cell["state"] in ("met", "unverified")
                self.assertEqual(1 if counts else 0, data.current_streak)
                self.assertEqual(not counts, heatmap_ui.colour(data, day) in ("s", "l0"))
                if cell["state"] == "unverified":
                    self.assertTrue(heatmap_ui.describe(data, day, english).endswith(" · Time not known"))


class UnverifiedDays(unittest.TestCase):
    def test_a_streak_runs_through_unverified_days(self):
        today = date(2026, 11, 20)
        verdicts = {date(2026, 11, day): heatmap.Verdict(state) for day, state in ((18, "met"), (19, "unverified"), (20, "met"))}
        data = heatmap.summarize(today, {day: 3 for day in verdicts}, {}, (), verdicts)
        self.assertEqual(3, data.current_streak)
        self.assertEqual("3 reviews · Time not known", heatmap_ui.describe(data, date(2026, 11, 19), english))

    def test_the_server_day_is_studied_with_time_not_known(self):
        profile = unverified_profile()
        found = day_verdict.verdict(profile, [], 1_000)
        view = day_verdict._for_display(profile, found)
        self.assertEqual("unverified", view["_day_status"])
        self.assertEqual("Studied today · time not known", board._day_label(view, english))
        self.assertIn("aq-pill aq-unverified", board.pills(view, None, english))
        self.assertEqual(moods.STUDIED, moods.day_state(view))

    def test_exact_minutes_from_unsent_reviews_wait_for_the_upload(self):
        profile = unverified_profile()
        found = day_verdict.verdict(profile, [{"id": 500, "time_ms": 600_000}], 1_000)
        self.assertEqual("syncing", day_verdict._for_display(profile, found)["_day_status"])

    def test_history_days_say_time_not_known(self):
        self.assertEqual("Time not known", heatmap_ui._state_label("unverified", english))


class ObservedXp(unittest.TestCase):
    def test_an_observed_row_is_marked_with_the_reason(self):
        row = {"user": "cerro", "display": "Cerro", "xp": 22, "xp_source": "observed"}
        html = board.board_row(2, row, False, english)
        self.assertIn(">Observed<", html)
        self.assertIn('title="Includes answers read from AnkiDroid without review times"', html)
        self.assertEqual("Cerro · Observed", board.row_title(row, english))

    def test_exact_and_older_rows_are_not_marked(self):
        for source in ({"xp_source": "exact"}, {}):
            with self.subTest(source=source):
                row = dict({"user": "ana", "display": "Ana", "xp": 5}, **source)
                self.assertNotIn("Observed", board.board_row(1, row, False, english))
                self.assertEqual("Ana", board.row_title(row, english))

    def test_observed_profile_xp_is_marked_beside_the_level(self):
        profile = {"level": 2, "xp_into_level": 10, "xp_for_next": 100, "xp_sources": {"all": "observed", "week": "observed"}}
        self.assertIn(">Observed<", board.pills(profile, None, english))
        self.assertIn("Observed", board.summary_parts(profile, None, english))
        profile["xp_sources"] = {"all": "exact"}
        self.assertNotIn("Observed", board.pills(profile, None, english))
        self.assertNotIn("Observed", board.summary_parts(profile, None, english))


if __name__ == "__main__":
    unittest.main()
