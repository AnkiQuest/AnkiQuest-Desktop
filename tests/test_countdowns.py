"""Countdowns follow tests/server-fixtures/countdowns.json, which the Android app tests against too."""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from addon_loader import ADDON, load_in_package

countdowns = load_in_package("aq_countdowns", "countdowns")
settings_sync = load_in_package("aq_countdowns", "settings_sync")
board = load_in_package("aq_countdowns", "board")
language = load_in_package("aq_countdowns", "language")

FIXTURE = json.loads((ADDON.parent / "tests/server-fixtures/countdowns.json").read_text("utf-8"))
SETTINGS = json.loads((ADDON.parent / "tests/server-fixtures/synced_settings.json").read_text("utf-8"))


def events(rows):
    return [countdowns.Event(row["name"], row["date"], row["deck"]) for row in rows]


def english(text):
    return text


def plural(one, other, count):
    return one if count == 1 else other


class SharedCases(unittest.TestCase):
    def test_days_follow_the_shared_cases(self):
        for case in FIXTURE["days"]:
            with self.subTest(case["name"]):
                now = datetime.strptime(case["now"], "%Y-%m-%dT%H:%M")
                today = countdowns.anki_today(now, case["day_start_hour"])
                found = countdowns.days(today, countdowns.parse_date(case["date"]))
                self.assertEqual(case["expected"], {"state": found.state.value, "days": found.days})

    def test_the_nearest_event_follows_the_shared_cases(self):
        for case in FIXTURE["nearest"]:
            with self.subTest(case["name"]):
                found = countdowns.nearest(events(case["events"]), countdowns.parse_date(case["today"]))
                self.assertEqual(case["expected"], found.name if found else None)

    def test_the_list_order_follows_the_shared_cases(self):
        for case in FIXTURE["order"]:
            with self.subTest(case["name"]):
                self.assertEqual(case["expected"], [event.name for event in countdowns.ordered(events(case["events"]))])

    def test_searches_follow_the_shared_cases(self):
        for case in FIXTURE["search"]:
            with self.subTest(case["name"]):
                self.assertEqual(case["expected"], countdowns.search(case["deck"], case["days"]))

    def test_pace_follows_the_shared_cases(self):
        for case in FIXTURE["pace"]:
            with self.subTest(case["name"]):
                found = countdowns.pace(case["days"], case["remaining"])
                expected = {"state": found.kind.value}
                if found.cards is not None:
                    expected["cards"] = found.cards
                self.assertEqual(case["expected"], expected)

    def test_the_wording_is_the_shared_english(self):
        wording = FIXTURE["wording"]
        spanish = countdowns.Event("Spanish exam", "2026-12-01", None)
        lines = {
            "upcoming": countdowns.headline(spanish, countdowns.Days(countdowns.State.UPCOMING, 12), english),
            "tomorrow": countdowns.headline(spanish, countdowns.Days(countdowns.State.TOMORROW, 1), english),
            "today": countdowns.headline(spanish, countdowns.Days(countdowns.State.TODAY, 0), english),
            "past": countdowns.headline(spanish, countdowns.Days(countdowns.State.PAST, -1), english),
        }
        for key, line in lines.items():
            with self.subTest(key):
                self.assertEqual(wording[key].format(name="Spanish exam", days=12), line)
        pace = {
            "pace_one": countdowns.pace_text(countdowns.pace(30, 1), "A1", plural, english),
            "pace_other": countdowns.pace_text(countdowns.pace(12, 300), "A1", plural, english),
            "done": countdowns.pace_text(countdowns.pace(12, 0), "A1", plural, english),
        }
        for key, line in pace.items():
            with self.subTest(key):
                cards = 1 if key == "pace_one" else 25
                self.assertEqual(wording[key].format(cards=cards, deck="A1"), line)
        self.assertIsNone(countdowns.pace_text(countdowns.pace(0, 5), "A1", plural, english))

    def test_every_label_is_the_shared_english(self):
        # Labels without placeholders appear in the add-on as written in the fixture.
        source = "".join(path.read_text("utf-8") for path in (ADDON / "countdowns_ui.py", ADDON / "board.py", ADDON / "ui.py"))
        for key in ("section", "empty", "add", "edit", "manage", "name", "date", "deck", "no_deck", "save", "delete",
                    "name_missing", "full", "private"):
            with self.subTest(key):
                self.assertIn('tr("%s")' % FIXTURE["wording"][key], source.replace("translate(", "tr("))


class Limits(unittest.TestCase):
    def test_limits_are_the_synced_setting_entry(self):
        row = next(row for row in SETTINGS["keys"] if row["key"] == "countdowns")
        self.assertEqual(
            (row["max_events"], row["max_name_chars"], row["max_deck_chars"]),
            (countdowns.MAX_EVENTS, countdowns.MAX_NAME_CHARS, countdowns.MAX_DECK_CHARS),
        )
        self.assertEqual(row["desktop"], countdowns.CONFIG_KEY)

    def test_the_add_on_accepts_exactly_the_lists_the_server_stores(self):
        for case in SETTINGS["server_merge"]:
            if "countdowns" not in case["incoming"]:
                continue
            with self.subTest(case["name"]):
                value = case["incoming"]["countdowns"]["value"]
                self.assertEqual(not case.get("refused", False), countdowns.valid(value))

    def test_an_unusable_list_counts_as_empty(self):
        self.assertEqual([], countdowns.events("Spanish exam"))
        self.assertEqual([], countdowns.events([{"name": " ", "date": "2026-12-01", "deck": None}]))


class Sync(unittest.TestCase):
    def test_countdowns_sync_only_with_a_server_that_keeps_them(self):
        self.assertNotIn("countdowns", settings_sync.synced({"settings_sync"}))
        self.assertIn("countdowns", settings_sync.synced({"settings_sync", "countdowns"}))

    def test_a_sync_without_countdowns_keeps_their_change_time(self):
        snapshot = {settings_sync.CHANGED_KEY: {"countdowns": 5}}
        updates, changed, _ = settings_sync.plan(snapshot, {}, settings_sync.synced({"settings_sync"}))
        settled, _ = settings_sync.settle(snapshot, dict(snapshot), updates, changed)
        self.assertEqual(5, settled[settings_sync.CHANGED_KEY]["countdowns"])

    def test_a_new_list_is_sent_with_its_change_time(self):
        value = [{"name": "Spanish exam", "date": "2026-12-01", "deck": None}]
        config = {"countdowns": value, settings_sync.CHANGED_KEY: {"countdowns": 7}}
        _, _, push = settings_sync.plan(config, {}, ["countdowns"])
        self.assertEqual({"countdowns": {"value": value, "updated_at": 7}}, push)


class TodayCard(unittest.TestCase):
    def test_the_card_shows_the_line_the_pace_and_the_list_button(self):
        html = board.countdown_card({"countdown": {"headline": "Spanish exam in 12 days", "pace": "~25 cards a day"}}, english)
        self.assertIn("Spanish exam in 12 days", html)
        self.assertIn("~25 cards a day", html)
        self.assertIn("ankiquest:countdowns", html)
        self.assertIn("Edit countdowns", html)

    def test_no_countdown_no_card(self):
        self.assertEqual("", board.countdown_card({"countdown": None}, english))
        self.assertEqual("", board.countdown_card({}, english))

    def test_every_language_keeps_the_order_of_name_and_days(self):
        for code in ("de", "es", "fr", "pt"):
            with self.subTest(code):
                line = language.tr("%s in %d days", code) % ("Spanish exam", 12)
                self.assertLess(line.index("Spanish exam"), line.index("12"))


if __name__ == "__main__":
    unittest.main()


class Forms(unittest.TestCase):
    """The real Qt forms run in their own process, away from tests that replace Anki."""

    def test_the_forms_keep_the_list_one_the_server_stores(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("qt_countdowns.py"))],
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
