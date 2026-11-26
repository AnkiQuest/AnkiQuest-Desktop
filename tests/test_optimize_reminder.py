"""The optimize reminder follows AnkiQuest-Server's tests/fixtures/optimize_reminder.json, as Android does."""

import json
import sqlite3
import unittest
from pathlib import Path

from addon_loader import load_in_package, load_module

rule = load_in_package("aq_optimize_reminder", "optimize_reminder")
settings_sync = load_in_package("aq_optimize_settings_sync", "settings_sync")
language = load_module("aq_optimize_language", "language.py")
FIXTURE = json.loads((Path(__file__).parent / "fixtures/optimize_reminder.json").read_text("utf-8"))
SETTINGS = json.loads((Path(__file__).parent / "fixtures/synced_settings.json").read_text("utf-8"))


class Revlog:
    """The revlog columns the count reads, behind Anki's `db.scalar`."""

    def __init__(self, reviews):
        self._db = sqlite3.connect(":memory:")
        self._db.execute("create table revlog (id integer primary key, type integer, ease integer)")
        self._db.executemany("insert into revlog values (?, ?, ?)", [(r["id"], r["type"], r["ease"]) for r in reviews])

    def scalar(self, sql, *args):
        return self._db.execute(sql, args).fetchone()[0]

    def close(self):
        self._db.close()


def found_verdict(verdict):
    if isinstance(verdict, rule.Silent):
        return {"verdict": verdict.quiet.value}
    return {"verdict": "remind", "since": verdict.since.value, "scheduler": verdict.wording.value}


class SharedCases(unittest.TestCase):
    def test_the_limits_are_the_shared_ones(self):
        limits = FIXTURE["limits"]
        self.assertEqual((limits["days"], limits["reviews"], limits["snooze_days"]), (rule.DAYS, rule.REVIEWS, rule.SNOOZE_DAYS))

    def test_every_preset_scheduler(self):
        self.assertTrue(FIXTURE["schedulers"])
        for case in FIXTURE["schedulers"]:
            with self.subTest(case["name"]):
                fsrs = rule.Fsrs.ON if case["fsrs"] else rule.Fsrs.OFF
                config = {key: case[key] for key in ("rwkvReviewEnabled", "rwkvReviewInstantOrderEnabled")}
                self.assertEqual(case["expected"], rule.scheduler(fsrs, config).value)

    def test_missing_rwkv_keys_mean_fsrs(self):
        self.assertIs(rule.Scheduler.FSRS, rule.scheduler(rule.Fsrs.ON, {}))

    def test_every_review_count(self):
        self.assertTrue(FIXTURE["reviews"])
        for case in FIXTURE["reviews"]:
            with self.subTest(case["name"]):
                revlog = Revlog(case["reviews"])
                found = rule.reviews_since(revlog, case["today"], case["day_cutoff"], case["last_optimized_day"])
                revlog.close()
                self.assertEqual(case["expected"], found)

    def test_every_verdict(self):
        self.assertTrue(FIXTURE["cases"])
        for case in FIXTURE["cases"]:
            with self.subTest(case["name"]):
                inputs = rule.Inputs(
                    today=case["today"],
                    last_optimized_day=case["last_optimized_day"],
                    reviews_since=case["reviews_since"],
                    presets=[rule.Scheduler(preset) for preset in case["presets"]],
                    deck=1,
                )
                found = rule.verdict(inputs, rule.decode(case["state"]))
                self.assertEqual(case["expected"], found_verdict(found))

    def test_every_transition(self):
        self.assertTrue(FIXTURE["transitions"])
        for case in FIXTURE["transitions"]:
            with self.subTest(case["name"]):
                found = rule.next_state(
                    rule.decode(case["state"]), rule.Event(case["event"]), case["today"], case["last_optimized_day"]
                )
                self.assertEqual(case["expected"], rule.encode(found))
                self.assertEqual(found, rule.decode(rule.encode(found)))

    def test_a_missing_or_broken_state_is_on(self):
        broken = (None, "on", {}, {"kind": "snoozed"}, {"kind": "dismissed"}, {"kind": "snoozed", "until_day": "x"},
                  {"kind": "off", "until_day": 3}, {"kind": "dismissed", "optimized_day": 0})
        for stored in broken:
            with self.subTest(stored=stored):
                self.assertEqual(rule.On(), rule.decode(stored))


class SyncedState(unittest.TestCase):
    """The state is the synced setting optimize_reminder, one for all the player's devices."""

    def test_the_state_is_the_synced_setting(self):
        row = next(row for row in SETTINGS["keys"] if row["key"] == "optimize_reminder")
        self.assertEqual((row["desktop"], row["default"]), (rule.CONFIG_KEY, rule.DEFAULT))
        self.assertEqual((rule.CONFIG_KEY, rule.DEFAULT, None), settings_sync.KEYS["optimize_reminder"])
        self.assertEqual(rule.On(), rule.decode(rule.DEFAULT))

    def test_a_snooze_here_is_a_change_to_send(self):
        snoozed = {"kind": "snoozed", "until_day": 507}
        self.assertEqual({"optimize_reminder": 5}, settings_sync.stamped({}, {rule.CONFIG_KEY: snoozed}, 5))
        self.assertIsNone(settings_sync.stamped({}, {rule.CONFIG_KEY: rule.encode(rule.On())}, 5))

        # A snooze from another device replaces the state here.
        updates, changed, push = settings_sync.plan({}, {"optimize_reminder": {"value": snoozed, "updated_at": 9}})
        self.assertEqual(({rule.CONFIG_KEY: snoozed}, 9, {}), (updates, changed["optimize_reminder"], push))

    def test_every_state_the_cases_name_is_usable(self):
        states = [case["state"] for case in FIXTURE["cases"]] + [case["expected"] for case in FIXTURE["transitions"]]
        for stored in states:
            with self.subTest(stored=stored):
                self.assertTrue(settings_sync.usable("optimize_reminder", stored))
                self.assertEqual(stored, rule.encode(rule.decode(stored)))

    def test_only_what_the_server_stores_is_usable(self):
        cases = [case for case in SETTINGS["server_merge"] if "optimize_reminder" in case["incoming"]]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case["name"]):
                value = case["incoming"]["optimize_reminder"]["value"]
                self.assertEqual(not case.get("refused", False), settings_sync.usable("optimize_reminder", value))
        self.assertFalse(rule.valid({"kind": "snoozed", "until_day": True}))
        self.assertFalse(rule.valid({"kind": "snoozed", "until_day": 2**31}))


class Wording(unittest.TestCase):
    TEXTS = {
        "title": rule.TITLE,
        "stale": rule.SINCE_TEXT[rule.Since.STALE],
        "never": rule.SINCE_TEXT[rule.Since.NEVER],
        "fsrs": rule.WORDING_TEXT[rule.Wording.FSRS],
        "rwkv": rule.WORDING_TEXT[rule.Wording.RWKV],
        "mixed": rule.WORDING_TEXT[rule.Wording.MIXED],
        "where": rule.WHERE,
        "open": rule.OPEN,
        "snooze": rule.SNOOZE,
        "dismiss": rule.DISMISS,
        "setting": rule.SETTING,
        "setting_summary": rule.SETTING_SUMMARY,
    }

    def test_the_wording_is_the_shared_english_in_its_order(self):
        self.assertEqual(FIXTURE["wording"], self.TEXTS)
        self.assertEqual(list(FIXTURE["wording"]), list(self.TEXTS))

    def test_the_message_is_since_then_scheduler_then_where(self):
        wording = FIXTURE["wording"]
        for since in rule.Since:
            for kind in rule.Wording:
                with self.subTest(since=since, wording=kind):
                    self.assertEqual(
                        " ".join(wording[key] for key in (since.value, kind.value, "where")),
                        rule.message(rule.Remind(since, kind), lambda text: text),
                    )

    def test_every_text_is_translated(self):
        # The texts reach tr through constants, so the label scan cannot see them.
        for code, table in language.TABLES.items():
            for key, text in self.TEXTS.items():
                with self.subTest(language=code, key=key):
                    self.assertIn(text, table)


class Collection:
    """The parts of an open collection the inputs read."""

    def __init__(self, config, presets, revlog):
        self._config = config
        self.sched = type("Sched", (), {"today": 500, "day_cutoff": 1794974400})()
        self.db = revlog
        self.decks = type("Decks", (), {"all_config": lambda _: presets, "get_current_id": lambda _: 7})()

    def get_config(self, key, default=None):
        return self._config.get(key, default)


class Inputs(unittest.TestCase):
    def test_reads_the_collection(self):
        revlog = Revlog([{"id": 1794900000000, "type": 1, "ease": 3}, {"id": 1, "type": 1, "ease": 3}])
        presets = [{"name": "Default"}, {"name": "RWKV", "rwkvReviewEnabled": True}]
        found = rule.inputs(Collection({"fsrs": True, "lastFsrsOptimize": 498}, presets, revlog))
        self.assertEqual(rule.Inputs(500, 498, 1, [rule.Scheduler.FSRS, rule.Scheduler.RWKV_CURVE], 7), found)

        # 0 or a missing key is never; FSRS off makes every preset SM-2.
        for config in ({"lastFsrsOptimize": 0}, {}):
            with self.subTest(config=config):
                found = rule.inputs(Collection(config, presets, revlog))
                self.assertEqual((None, 2, [rule.Scheduler.SM2] * 2), (found.last_optimized_day, found.reviews_since, found.presets))
        revlog.close()


if __name__ == "__main__":
    unittest.main()
