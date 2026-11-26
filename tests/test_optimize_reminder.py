"""The optimize reminder follows AnkiQuest-Server's tests/fixtures/optimize_reminder.json, as Android does."""

import json
import sqlite3
import unittest
from pathlib import Path

from addon_loader import load_in_package, load_module

rule = load_in_package("aq_optimize_reminder", "optimize_reminder")
language = load_module("aq_optimize_language", "language.py")
FIXTURE = json.loads((Path(__file__).parent / "fixtures/optimize_reminder.json").read_text("utf-8"))


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
        for stored in (None, "on", {}, {"kind": "snoozed"}, {"kind": "dismissed"}, {"kind": "snoozed", "until_day": "x"}):
            with self.subTest(stored=stored):
                self.assertEqual(rule.On(), rule.decode(stored))


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
