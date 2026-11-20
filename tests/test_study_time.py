"""Study time follows AnkiQuest-Server's tests/fixtures/study_time.json, as Android does."""

import json
import sqlite3
import unittest
from pathlib import Path

from addon_loader import load_in_package

study_time = load_in_package("aq_study_time", "study_time")
FIXTURE = json.loads((Path(__file__).parent / "fixtures/study_time.json").read_text("utf-8"))


class Revlog:
    """The revlog columns study time reads, behind Anki's `db.all`."""

    def __init__(self, reviews):
        self._db = sqlite3.connect(":memory:")
        self._db.execute("create table revlog (id integer primary key, time integer, type integer, ease integer)")
        self._db.executemany("insert into revlog values (?, ?, ?, ?)",
                             [(r["id"], r["time_ms"], r["type"], r["ease"]) for r in reviews])

    def all(self, sql, *args):
        return self._db.execute(sql, args).fetchall()

    def close(self):
        self._db.close()


class SharedCases(unittest.TestCase):
    def test_every_case(self):
        self.assertTrue(FIXTURE["cases"])
        for case in FIXTURE["cases"]:
            with self.subTest(case["name"]):
                clock = case["clock"]
                revlog = Revlog(case["reviews"])
                totals = study_time.load(revlog, case["now_ms"], clock["offset_west_min"], clock["rollover_hour"])
                revlog.close()
                expected = case["expected"]
                self.assertEqual(expected["today"], totals.today.isoformat())
                self.assertEqual(
                    [expected[key] for key in ("today_ms", "week_ms", "month_ms", "total_ms", "study_days", "average_ms")],
                    [totals.today_ms, totals.week_ms, totals.month_ms, totals.total_ms, totals.study_days, totals.average_ms],
                )

    def test_durations(self):
        for case in FIXTURE["durations"]:
            with self.subTest(ms=case["ms"]):
                expected = ("%d min" % case["minutes"] if case["hours"] == 0
                            else "%d h %d min" % (case["hours"], case["minutes"]))
                self.assertEqual(expected, study_time.duration(case["ms"]))

    def test_translated_durations(self):
        self.assertEqual("1 Std. 30 Min.", study_time.duration(5_430_000, {"%d h %d min": "%d Std. %d Min."}.get))


if __name__ == "__main__":
    unittest.main()
