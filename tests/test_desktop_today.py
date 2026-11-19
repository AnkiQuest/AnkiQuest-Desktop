"""Desktop Today panel, daily goal, deck states and session recaps; run with python -m unittest discover -s tests."""

import ast
import re
import sqlite3
import sys
import time
import unittest
from concurrent.futures import Future
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import Mock, patch

from addon_loader import ADDON, fake_anki, load_in_package, load_module

goals = load_in_package("ankiquest_today_test", "goals")
moods = load_module("ankiquest_moods", "moods.py")
today = load_in_package("ankiquest_today_test", "today")
board = load_in_package("ankiquest_today_test", "board")
language = load_in_package("ankiquest_today_test", "language")
progress = load_module("ankiquest_today_progress", "deck_completion.py")


def node(deck_id, name="", new=0, review=0, learn=0, intraday=0, children=()):
    return SimpleNamespace(
        deck_id=deck_id, name=name, new_count=new, review_count=review, learn_count=learn,
        intraday_learning=intraday, children=list(children),
    )


def database():
    db = sqlite3.connect(":memory:")
    db.executescript(
        "create table cards (id integer, did integer, odid integer, queue integer, due integer, odue integer);"
        "create table revlog (id integer, cid integer, ease integer, type integer, time integer);"
    )
    return db


def collection(db, tree, today_number=100, cutoff=1_000_000):
    return SimpleNamespace(
        sched=SimpleNamespace(today=today_number, day_cutoff=cutoff, deck_due_tree=lambda: tree),
        db=SimpleNamespace(
            all=lambda sql, *args: db.execute(sql, args).fetchall(),
            first=lambda sql, *args: db.execute(sql, args).fetchone(),
            scalar=lambda sql, *args: db.execute(sql, args).fetchone()[0],
        ),
    )


def verdict(met, minutes=10, streak_minutes=5, waiting=False):
    """A day_verdict.verdict answer for today."""
    return {
        "met": met, "streak_state": "studied" if met else "pending", "streak": 1, "reviews": 1,
        "time_ms": minutes * 60_000, "minutes": minutes, "streak_minutes": streak_minutes,
        "unsent": 1 if waiting else 0, "waiting": waiting,
    }


def backlog_plan(days=30, since=1000, chosen=True):
    return goals.Plan("backlog", days, since, chosen)


class GoalTests(unittest.TestCase):
    me = ["https://quest.example", "hill"]

    def test_the_servers_goal_is_read_with_its_defaults_and_limits(self):
        self.assertEqual(goals.Plan("backlog", 30, 5, False), goals.plan(None, 5))
        self.assertEqual(goals.Plan("backlog", 30, 5, False), goals.plan({"mode": "nonsense"}, 5))
        self.assertEqual(goals.Plan("cards", 5000, 3, True), goals.plan({"mode": "cards", "value": 9999, "since": 3, "chosen": True}, 5))
        self.assertEqual(goals.Plan("minutes", 20, 5, False), goals.plan({"mode": "minutes"}, 5))
        self.assertEqual("off", goals.plan({"mode": "off", "value": 100, "since": 4, "chosen": True}, 5).mode)

    def test_the_goal_is_remembered_per_account_and_a_profile_keeps_chosen(self):
        other = ["https://quest.example", "cerro"]
        found, stored = goals.remembered_plan({"mode": "cards", "value": 80, "since": 4, "chosen": True}, None, self.me, 9)
        self.assertEqual(goals.Plan("cards", 80, 4, True), found)
        again, kept = goals.remembered_plan({"mode": "cards", "value": 90, "since": 9}, stored, self.me, 9)
        self.assertEqual(goals.Plan("cards", 90, 9, True), again)
        self.assertEqual((again, kept), goals.remembered_plan(None, kept, self.me, 9))
        self.assertEqual((goals.default_plan(9), None), goals.remembered_plan(None, kept, other, 9))

    def test_the_backlog_plan_spreads_what_is_left_over_the_days_left(self):
        load = goals.Load(5, 12, 9, 30, 200)
        fixed, restart = goals.goal(load, backlog_plan(30, since=1000), 1000)
        self.assertEqual(goals.Goal(12 + 30 + 7, 200, 7, 30), fixed)
        self.assertFalse(restart)
        late, _ = goals.goal(goals.Load(5, 0, 0, 10, 9), backlog_plan(30, since=1000), 1028)
        self.assertEqual(goals.Goal(10 + 5, 9, 5, 2), late)
        last, _ = goals.goal(goals.Load(5, 0, 0, 10, 9), backlog_plan(30, since=1000), 1029)
        self.assertEqual(9, last.extra)
        self.assertEqual(1, goals.backlog_extra(3, 30))
        self.assertEqual(0, goals.backlog_extra(0, 30))

    def test_a_plan_that_ran_out_starts_again(self):
        fixed, restart = goals.goal(goals.Load(5, 0, 0, 10, 60), backlog_plan(30, since=1000), 1030)
        self.assertTrue(restart)
        self.assertEqual(goals.Goal(10 + 2, 60, 2, 30), fixed)

    def test_cards_minutes_and_off(self):
        load = goals.Load(5, 12, 9, 30, 200)
        self.assertEqual((goals.Goal(100, 0, 0, None), False), goals.goal(load, goals.Plan("cards", 100, 1, True), 9))
        self.assertEqual((goals.Goal(15, 0, 0, None), False), goals.goal(load, goals.Plan("minutes", 15, 1, True), 9))
        self.assertEqual((None, False), goals.goal(load, goals.Plan("off", 100, 1, True), 9))

    def test_the_goal_is_fixed_for_the_day_until_the_goal_changes(self):
        chosen = backlog_plan(10, since=1000)
        first, stored, _ = goals.fixed_goal(goals.Load(5, 0, 0, 40, 100), chosen, 1000, None)
        self.assertEqual(50, first.target)
        later, kept, restart = goals.fixed_goal(goals.Load(5, 30, 12, 10, 100), chosen, 1000, stored)
        self.assertEqual((first, stored, False), (later, kept, restart))
        tomorrow, _, _ = goals.fixed_goal(goals.Load(6, 0, 0, 10, 0), chosen, 1001, stored)
        self.assertEqual(10, tomorrow.target)
        changed, _, _ = goals.fixed_goal(goals.Load(5, 30, 12, 10, 100), goals.Plan("cards", 100, 1000, True), 1000, stored)
        self.assertEqual(100, changed.target)
        off, record, _ = goals.fixed_goal(goals.Load(5, 0, 0, 40, 100), chosen._replace(mode="off"), 1000, stored)
        self.assertIsNone(off)
        self.assertEqual((None, record, False), goals.fixed_goal(goals.Load(5, 3, 1, 40, 100), chosen._replace(mode="off"), 1000, record))

    def test_the_servers_count_is_used_for_todays_cards_and_minutes(self):
        chosen = goals.Plan("cards", 50, 1, True)
        profile = {"goal": {"mode": "cards", "value": 50, "since": 1, "day": 9, "progress": 40, "reached": False}}
        status, _, _ = goals.status(goals.Load(5, 30, 9, 0, 0), chosen, 9, None, 0, profile)
        self.assertEqual(40, status.progress)
        self.assertFalse(status.goal_done)
        stale, _, _ = goals.status(goals.Load(5, 30, 9, 0, 0), chosen, 10, None, 0, profile)
        self.assertEqual(30, stale.progress)
        reached = {"goal": dict(profile["goal"], reached=True)}
        self.assertTrue(goals.status(goals.Load(5, 30, 9, 0, 0), chosen, 9, None, 0, reached)[0].goal_done)
        other = {"goal": dict(profile["goal"], mode="minutes")}
        self.assertIsNone(goals.status(goals.Load(5, 30, 9, 0, 0), chosen, 9, None, 0, other)[0].served)

    def test_minimum_follows_the_servers_verdict_and_goal_its_rule(self):
        status = goals.Status(5, 4, 5, 10, "cards", goals.Goal(10, 0, 0, None), None, False)
        self.assertFalse(status.minimum_done, "the collection alone never secures the streak")
        self.assertTrue(status.goal_done)
        self.assertFalse(status._replace(minutes=9).minimum_done)
        self.assertEqual(4, status.minimum_minutes)
        short = status._replace(verdict=verdict(False, minutes=3))
        self.assertFalse(short.minimum_done)
        self.assertEqual(3, short.minimum_minutes)
        self.assertTrue(status._replace(verdict=verdict(True)).minimum_done)
        self.assertFalse(status._replace(verdict=verdict(True)).minimum_waiting)
        waiting = status._replace(verdict=verdict(True, waiting=True))
        self.assertTrue(waiting.minimum_done and waiting.minimum_waiting)
        self.assertIn("once your reviews upload", goals.minimum_text(waiting))
        self.assertIn("once your reviews upload", goals.minimum_text(waiting._replace(streak_minutes=0)))
        self.assertTrue(goals.minimum_text(status._replace(verdict=verdict(True))).startswith("Streak secured:"))
        self.assertEqual(4, status._replace(mode="minutes").progress)
        self.assertFalse(status._replace(goal=None).goal_done)

    def test_the_verdict_brings_the_servers_minimum(self):
        found, _, _ = goals.status(goals.Load(5, 3, 2, 0, 0), goals.Plan("off", None, 1, True), 9, None, 5, None, verdict(False, streak_minutes=15))
        self.assertEqual(15, found.streak_minutes)
        self.assertEqual(5, goals.status(goals.Load(5, 3, 2, 0, 0), goals.Plan("off", None, 1, True), 9, None, 5)[0].streak_minutes)

    def test_each_celebration_shows_once_a_day(self):
        chosen = backlog_plan(30, since=1000)
        stored, shown = None, None

        def claim(load):
            nonlocal stored, shown
            met = load.studied_cards > 0 and load.minutes >= 5
            status, stored, _ = goals.status(load, chosen, 1000 + load.day, stored, 5, None, verdict(met, minutes=load.minutes))
            earned, shown = goals.claim(status, shown)
            return earned

        claim(goals.Load(5, 0, 0, 20, 0))
        self.assertIsNone(claim(goals.Load(5, 3, 2, 17, 0)))
        self.assertEqual(goals.MINIMUM, claim(goals.Load(5, 8, 6, 12, 0)))
        self.assertIsNone(claim(goals.Load(5, 9, 7, 11, 0)))
        self.assertEqual(goals.GOAL, claim(goals.Load(5, 20, 15, 0, 0)))
        self.assertIsNone(claim(goals.Load(5, 21, 16, 0, 0)))
        claim(goals.Load(6, 0, 0, 5, 0))
        self.assertEqual(goals.BOTH, claim(goals.Load(6, 5, 6, 0, 0)))

    def test_a_server_with_wins_celebrates_the_goal_instead(self):
        status = goals.Status(5, 9, 0, 20, "backlog", goals.Goal(20, 4, 1, 4), None, False, verdict(True, streak_minutes=0))
        self.assertTrue(status.minimum_done and status.goal_done)
        earned, stored = goals.claim(status, None, server_goal=True)
        self.assertEqual(goals.MINIMUM, earned)
        self.assertNotIn("Next up", goals.celebration_text(earned, status))
        self.assertIsNone(goals.claim(status, stored, server_goal=True)[0])
        self.assertEqual(goals.BOTH, goals.claim(status, None)[0], "the fallback for older servers")

    def test_a_reached_backlog_goal_is_reported_once_a_day(self):
        done = goals.Status(5, 9, 0, 20, "backlog", goals.Goal(20, 4, 1, 4), None, False)
        self.assertTrue(goals.to_report(done, self.me, 1000, None))
        told = {"account": self.me, "day": 1000}
        self.assertFalse(goals.to_report(done, self.me, 1000, told))
        self.assertTrue(goals.to_report(done, self.me, 1001, told))
        self.assertTrue(goals.to_report(done, ["https://quest.example", "cerro"], 1000, told))
        self.assertFalse(goals.to_report(done._replace(studied_cards=3), self.me, 1000, None))
        self.assertFalse(goals.to_report(done._replace(reached=True), self.me, 1000, None))
        self.assertFalse(goals.to_report(done._replace(mode="cards"), self.me, 1000, None))

    def test_an_older_add_ons_goal_moves_to_the_server(self):
        self.assertIsNone(goals.legacy_goal({}))
        self.assertIsNone(goals.legacy_goal({"goal_mode": "backlog", "goal_backlog_percent": 10}))
        for percent, days in ((5, 60), (20, 14), (34, 7), (100, 1)):
            self.assertEqual({"mode": "backlog", "value": days}, goals.legacy_goal({"goal_mode": "backlog", "goal_backlog_percent": percent}))
        self.assertEqual({"mode": "cards", "value": 5000}, goals.legacy_goal({"goal_mode": "cards", "goal_cards": 9000}))
        self.assertEqual({"mode": "minutes", "value": 15}, goals.legacy_goal({"goal_mode": "minutes", "goal_minutes": 15}))
        self.assertEqual({"mode": "off"}, goals.legacy_goal({"goal_mode": "off"}))

    def test_streak_minimum_is_remembered_per_account(self):
        me, other = self.me, ["https://quest.example", "cerro"]
        minutes, stored = goals.remembered_streak_minutes({"today": {"streak_minutes": 7}}, None, me)
        self.assertEqual(7, minutes)
        self.assertEqual((7, stored), goals.remembered_streak_minutes(None, stored, me))
        self.assertEqual(0, goals.remembered_streak_minutes(None, stored, other)[0])
        self.assertEqual(0, goals.remembered_streak_minutes({"today": {"streak_minutes": -3}}, stored, me)[0])

    def test_texts_say_what_is_left(self):
        status = goals.Status(5, 3, 10, 4, "cards", goals.Goal(50, 0, 0, None), None, False)
        self.assertEqual("Streak minimum: 10 minutes of review today", goals.minimum_text(status))
        self.assertEqual("4 of 50 cards", goals.progress_text(status))
        self.assertEqual("Any review today keeps your streak going.", goals.minimum_text(status._replace(streak_minutes=0, studied_cards=0)))
        done = status._replace(minutes=10)
        self.assertEqual("Streak secured! 🔥", goals.celebration_title(goals.MINIMUM))
        self.assertIn("Next up, your daily goal: 4 of 50 cards so far.", goals.celebration_text(goals.MINIMUM, done))
        self.assertNotIn("Next up", goals.celebration_text(goals.MINIMUM, done._replace(goal=None)))
        self.assertEqual("12 of 12 minutes", goals.progress_text(status._replace(mode="minutes", minutes=30, goal=goals.Goal(12, 0, 0, None))))
        spanish = lambda value: language.tr(value, "es")
        self.assertEqual("4 de 50 tarjetas", goals.progress_text(status, spanish))
        backlog = status._replace(mode="backlog", goal=goals.Goal(40, 90, 3, 30))
        self.assertEqual("Today’s due cards plus 3 of your 90 overdue cards, so the backlog is gone in 30 days.", goals.backlog_text(backlog))
        self.assertIn("in 1 day.", goals.backlog_text(backlog._replace(goal=goals.Goal(40, 3, 3, 1))))
        self.assertIsNone(goals.backlog_text(backlog._replace(goal=goals.Goal(40, 0, 0, 30))))
        self.assertIsNone(goals.backlog_text(status))

    def test_load_reads_todays_work_and_backlog(self):
        db = database()
        cutoff = 1_000_000
        start_ms = (cutoff - 86_400) * 1000
        rows = [
            (1, 1, 0, 2, 100, 0), (2, 1, 0, 2, 100, 0), (3, 1, 0, 2, 90, 0), (4, 1, 0, 2, 105, 0),
            (5, 9, 1, 2, 0, 80), (6, 1, 0, 1, cutoff - 10, 0), (7, 1, 0, 1, cutoff + 10, 0), (8, 1, 0, 3, 100, 0),
        ]
        db.executemany("insert into cards values (?, ?, ?, ?, ?, ?)", rows)
        db.executemany("insert into revlog values (?, ?, ?, ?, ?)", [
            (start_ms + 1, 1, 3, 1, 60_000), (start_ms + 2, 1, 3, 1, 30_000), (start_ms + 3, 2, 3, 1, 50_000),
            (start_ms - 1, 3, 3, 1, 999_999), (start_ms + 4, 3, 0, 4, 999_999),
        ])
        tree = node(0, children=[node(1, new=4), node(2, new=3)])
        load = goals.load(collection(db, tree, 100, cutoff))
        self.assertEqual(goals.Load(100, 2, 2, 2 + 2 + 7, 2), load)


class ProjectionTests(unittest.TestCase):
    forecast = goals.Forecast(due=40, backlog=300, daily_due=50, seconds_per_card=10)

    def test_each_choice_is_estimated_as_the_spec_says(self):
        self.assertEqual(goals.Projection(40 + 10, 500, 30), goals.projection("backlog", 30, self.forecast))
        self.assertEqual(goals.Projection(80, 800, 10), goals.projection("cards", 80, self.forecast))
        self.assertEqual(goals.Projection(50, 500, None), goals.projection("cards", 50, self.forecast))
        self.assertEqual(goals.Projection(60, 600, 30), goals.projection("minutes", 10, self.forecast))
        self.assertIsNone(goals.projection("off", None, self.forecast))
        clear = self.forecast._replace(backlog=0)
        self.assertEqual(goals.Projection(40, 400, 0), goals.projection("backlog", 7, clear))
        self.assertEqual(0, goals.projection("cards", 10, clear).cleared_in)

    def test_the_smallest_goal_that_shrinks_the_backlog(self):
        self.assertEqual(51, goals.shrinking_pace(self.forecast))
        self.assertEqual(50, goals.shrinking_pace(self.forecast._replace(backlog=0)))

    def test_the_summary_reads_naturally(self):
        self.assertEqual([
            "Cards today: about 50",
            "Time today: about 8 minutes",
            "Backlog cleared in 30 days",
            "To shrink your backlog, study at least 51 cards a day.",
        ], goals.summary("backlog", 30, self.forecast))
        self.assertIn("At this pace your backlog is never cleared.", goals.summary("cards", 20, self.forecast))
        clear = goals.summary("cards", 1, self.forecast._replace(backlog=0, daily_due=0, seconds_per_card=8))
        self.assertIn("Time today: less than a minute", clear)
        self.assertIn("Nothing overdue", clear)
        self.assertIn("Nothing overdue. About 0 cards a day keeps it that way.", clear)
        self.assertEqual(2, len(goals.summary("off", None, self.forecast)))
        self.assertEqual([], goals.summary("cards", 10, None))
        spanish = lambda value: language.tr(value, "es")
        self.assertIn("Atraso resuelto en 30 días", goals.summary("backlog", 30, self.forecast, spanish))

    def collection(self, cards, answers, today=100, cutoff=10_000_000):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.executescript(
            "create table cards (id integer, odid integer, type integer, queue integer, due integer, odue integer);"
            "create table revlog (id integer, ease integer, type integer, time integer);"
        )
        db.executemany("insert into cards values (?, ?, ?, ?, ?, ?)", cards)
        db.executemany("insert into revlog values (?, ?, ?, ?)", answers)
        return SimpleNamespace(
            sched=SimpleNamespace(today=today, day_cutoff=cutoff),
            db=SimpleNamespace(scalar=lambda sql, *args: db.execute(sql, args).fetchone()[0]),
        )

    def test_daily_due_averages_review_cards_over_the_next_week(self):
        cards = [(i, 0, 2, 2, 101 + i % 7, 0) for i in range(70)]
        cards += [(100, 0, 2, 2, 100, 0), (101, 0, 2, 2, 90, 0), (102, 0, 2, 2, 108, 0)]
        cards += [(103, 0, 2, -1, 102, 0), (104, 0, 1, 1, 102, 0), (105, 5, 2, 2, 0, 103)]
        self.assertEqual(10, goals.daily_due(self.collection(cards, [])))

    def test_answer_time_comes_from_the_last_30_days_or_defaults_to_8_seconds(self):
        cutoff = 10_000_000
        recent = (cutoff - 5 * 86_400) * 1000
        old = (cutoff - 40 * 86_400) * 1000
        answers = [(recent, 3, 1, 6000), (recent + 1, 3, 1, 12000), (old, 3, 1, 60000), (recent + 2, 0, 4, 90000)]
        self.assertEqual(9.0, goals.seconds_per_card(self.collection([], answers, cutoff=cutoff)))
        self.assertEqual(8, goals.seconds_per_card(self.collection([], [], cutoff=cutoff)))

    def test_server_calls(self):
        sent = []
        api = SimpleNamespace(user="hill", _request=lambda path, body=None, method=None: sent.append((path, body, method)) or {"mode": "cards"})
        goals.put(api, "backlog", 14, restart=True)
        goals.put(api, "off", 14)
        goals.fetch(api)
        self.assertEqual([
            ("/api/goal/hill", {"mode": "backlog", "value": 14, "restart": True}, "PUT"),
            ("/api/goal/hill", {"mode": "off"}, "PUT"),
            ("/api/goal/hill", None, None),
        ], sent)

        def empty(path, body=None, method=None):
            sent.append((path, body))
            raise ValueError("Expecting value")

        goals.report_reached(SimpleNamespace(user="hill", _request=empty), 20391)
        self.assertEqual(("/api/goal/hill/reached", {"day": 20391}), sent[-1])


class MoodTests(unittest.TestCase):
    now = 1_000_000

    def profile(self, state, reviews, ends=2_000_000):
        return {"streak_state": state, "today": {"reviews": reviews}, "day_ends_at": ends}

    def test_moods_follow_the_phone(self):
        self.assertEqual(moods.FREEZE, moods.mood(moods.FROZEN_1, [5], 5, self.profile("protected", 0), self.now))
        self.assertEqual(moods.WAITING, moods.mood(moods.SAD, [5], 5, self.profile("pending", 0), self.now))
        self.assertEqual(moods.CELEBRATE, moods.mood(moods.FIRE, [0, 0], 0, self.profile("studied", 4), self.now))
        self.assertEqual(moods.REVIEW, moods.mood(moods.FIRE, [3, 0], 3, self.profile("studied", 4), self.now))
        self.assertEqual(moods.STREAK, moods.mood(moods.FIRE, [], 0, self.profile("studied", 4), self.now))
        self.assertEqual(moods.WELCOME, moods.mood(moods.MOOD_UNKNOWN, [0], 0, None, self.now))

    def test_a_profile_from_an_ended_day_is_ignored(self):
        stale = self.profile("studied", 4, ends=self.now)
        self.assertEqual(moods.WELCOME, moods.mood(moods.MOOD_UNKNOWN, [0], 0, stale, self.now))

    def test_art_respects_the_companion(self):
        self.assertEqual("aki_freeze", moods.art("aki", moods.FREEZE))
        self.assertEqual("ankilope_frozen", moods.art("ankilope", moods.FREEZE))
        self.assertEqual("ankilope_celebrate", moods.art("ankilope", moods.WINNER))
        self.assertIsNone(moods.art("none", moods.REVIEW))
        self.assertIn("Aki", moods.message("aki", moods.WELCOME, 0)[0])
        self.assertNotIn("Aki", moods.message("ankilope", moods.WELCOME, 0)[0])

    def test_the_review_mood_keeps_its_pose_but_has_no_line(self):
        self.assertEqual("aki_review", moods.art("aki", moods.REVIEW))
        self.assertEqual((None, ()), moods.message("aki", moods.REVIEW, 0))
        self.assertEqual((None, ()), moods.message("ankilope", moods.REVIEW, 0))

    def test_every_mood_but_review_has_a_line(self):
        # MOODS and MESSAGES are separate lists; keep them from drifting apart.
        self.assertEqual(set(moods.MOODS) - {moods.REVIEW}, set(moods.MESSAGES))


class DeckDayTests(unittest.TestCase):
    def test_status_order_matches_the_phone(self):
        self.assertEqual(today.REVIEW_NOW, today.daily_status(1, 3, 0, 5))
        self.assertEqual(today.LEARNING_LATER, today.daily_status(0, 3, 4, 5))
        self.assertEqual(today.REVIEW_NOW, today.daily_status(0, 3, 4, None))
        self.assertEqual(today.DONE, today.daily_status(0, 0, 4, None))
        self.assertEqual(today.NOTHING, today.daily_status(0, 0, 0, None))

    def tree(self):
        return node(0, children=[
            node(1, "Spanish", review=2, children=[node(2, "Verbs", review=2)]),
            node(3, "Geography"),
            node(4, "Filtered", new=1),
        ])

    def snapshots(self):
        return [
            {"id": "1", "name": "Spanish", "remaining": 4, "reviewed_today": 6},
            {"id": "2", "name": "Spanish::Verbs", "remaining": 4, "reviewed_today": 6},
            {"id": "3", "name": "Geography", "remaining": 2, "reviewed_today": 1},
        ]

    def test_learning_later_rolls_up_to_parents(self):
        days = {day.id: day for day in today.deck_days(self.tree(), self.snapshots(), [(2, 2, 7200), (3, 2, 3600)])}
        self.assertEqual("Spanish::Verbs", days[2].name)
        self.assertEqual(today.REVIEW_NOW, days[1].status)
        self.assertEqual(2, days[1].ready_count)
        self.assertEqual(7_200_000, days[1].next_at)
        self.assertEqual(today.LEARNING_LATER, days[3].status)
        self.assertEqual(3_600_000, days[3].next_at)
        self.assertEqual((1, today.REVIEW_NOW), (days[4].ready_count, days[4].status))
        self.assertEqual([1, 2, 3, 4], [day.id for day in today.deck_days(self.tree(), self.snapshots(), [])])

    def test_load_days_queries_learning_due_before_rollover(self):
        db = database()
        db.executemany("insert into cards values (?, ?, ?, ?, ?, ?)", [
            (1, 3, 0, 1, 2000, 0), (2, 3, 0, 1, 1500, 0), (3, 3, 0, 1, 900, 0), (4, 3, 0, 1, 9000, 0), (5, 9, 3, 1, 1200, 0),
        ])
        col = collection(db, self.tree(), cutoff=5000)
        days = {day.id: day for day in today.load_days(col, 1_000_000, self.tree(), self.snapshots())}
        self.assertEqual(1_200_000, days[3].next_at)
        self.assertEqual(0, days[3].ready)

    def test_focus_prefers_the_selected_deck_with_work(self):
        days = today.deck_days(self.tree(), self.snapshots(), [(3, 2, 3600)])
        self.assertEqual(4, today.focus(days, 4).id)
        self.assertEqual(1, today.focus(days, 3).id)
        done = [day._replace(review=0, new=0, ready=0, remaining=0) for day in days]
        self.assertEqual(3, today.focus(done, 3).id)
        self.assertEqual(1, today.focus(done, 99).id)
        self.assertIsNone(today.focus([], 1))

    def test_labels_and_badges(self):
        days = {day.id: day for day in today.deck_days(self.tree(), self.snapshots(), [(3, 2, 3600)])}
        at = lambda ms: "at %d" % (ms // 1000)
        self.assertEqual("4 cards ready", today.label(days[1], show_time=at))
        self.assertEqual("1 card ready", today.label(days[4], show_time=at))
        self.assertEqual("Learning later today · next at at 3600", today.label(days[3], show_time=at))
        self.assertEqual("Done today", today.label(days[1]._replace(review=0, ready=0, remaining=0)))
        self.assertEqual("", today.badge(days[1]._replace(review=0, ready=0, remaining=0, reviewed=0)))
        self.assertIn("ankiquest-learning-later", today.badge(days[3], show_time=at))

    def test_badges_land_after_each_deck_name_in_ankis_markup(self):
        markup = (
            "<tr class='deck current' id='1'><td class=decktd colspan=5>"
            "<a class=collapse href=# onclick='return pycmd(\"collapse:1\")'>-</a>"
            "<a class=\"deck \" href=# onclick=\"return pycmd('open:1')\">Spanish </a></td></tr>"
            "<tr class='deck' id='3'><td><a class=deck href=# onclick=\"return pycmd('open:3')\">Geo&lt;graphy</a></td></tr>"
            "<tr class='deck' id='77'><td><a class=deck href=# onclick=\"return pycmd('open:77')\">Unknown</a></td></tr>"
        )
        days = today.deck_days(self.tree(), self.snapshots(), [(3, 2, 3600)])
        decorated = today.decorate(markup, days, show_time=lambda ms: "10:00")
        self.assertIn("Spanish </a><span class='ankiquest-day ankiquest-review-now'", decorated)
        self.assertIn("Geo&lt;graphy</a><span class='ankiquest-day ankiquest-learning-later'", decorated)
        self.assertIn("Unknown</a></td>", decorated)
        self.assertIn("pycmd(\"collapse:1\")'>-</a><a", decorated)


class PeriodTests(unittest.TestCase):
    def test_an_unknown_period_falls_back_to_the_week(self):
        self.assertEqual("week", today.period("decade"))


class SessionTests(unittest.TestCase):
    def test_a_session_counts_reviews_from_the_log(self):
        db = database()
        db.executemany("insert into revlog values (?, ?, ?, ?, ?)", [
            (1000, 1, 3, 1, 70_000), (2000, 2, 3, 1, 80_000), (3000, 3, 0, 4, 9_000), (500, 4, 3, 1, 1),
        ])
        col = collection(db, node(0))
        summary = today.session(col, 900, 5000, 12)
        self.assertEqual({"reviews": 2, "minutes": 2, "remaining": 12, "finished_at": 5000}, summary)
        self.assertIsNone(today.session(col, 3500, 5000, 0))
        self.assertIsNone(today.session(col, 0, 5000, 0))
        self.assertIsNone(today.session(col, 1, 1 + today.MAX_SESSION_MS + 1, 0))
        self.assertEqual("2 reviews · 2 minutes · 12 ready at session end", today.session_text(summary))
        self.assertEqual("less than a minute", today.duration(0))
        self.assertEqual("1 minute", today.duration(1))


class PanelTests(unittest.TestCase):
    def view(self, **changes):
        view = {
            "art": "/_addons/1/art/aki_review.png",
            "mood": "You showed up today. That is progress worth keeping.",
            "winner": "/_addons/1/art/aki_winner.png",
            "focus": {"id": 7, "name": "Spa<b>nish", "review": 3, "learning": 1, "new": 2,
                      "status": "review_now", "label": "6 cards ready", "ready": 6},
            "goal": {"minimum": "Streak minimum: 5 minutes of review today", "minimum_meter": (2, 5),
                     "daily": "Daily goal: 4 of 50 cards", "daily_meter": (4, 50), "backlog": None},
            "board": {"period": "day", "rows": [(1, {"display": "<img src=x>", "xp": 1200}, False), (6, {"user": "hill", "xp": 3}, True)]},
            "session": "12 reviews · 3 minutes · 0 ready at session end",
        }
        view.update(changes)
        return view

    profile = {"level": 3, "streak": 4, "quests": [
        {"title": "<script>alert(1)</script>", "progress": 3, "target": 10, "done": False, "reward": 20},
        {"title": "Combo", "progress": 5, "target": 5, "done": True, "reward": 15},
    ]}

    def test_the_panel_shows_every_part(self):
        html = board.html(self.profile, 2, 0, today=self.view())
        self.assertIn("aki_review.png", html)
        self.assertIn("You showed up today. That is progress worth keeping.", html)
        self.assertIn("4 day streak", html)
        self.assertIn("pycmd('ankiquest:study:7')", html)
        self.assertIn("Study 6 due", html)
        self.assertIn("aria-valuenow=2 aria-valuemax=5", html)
        self.assertIn("aria-valuenow=4 aria-valuemax=50", html)
        self.assertIn("Complete · 15 XP", html)
        self.assertIn("<option value=day selected>", html)
        self.assertIn("<div class='aq-player aq-me'><span class=aq-place>#6</span>", html)
        self.assertIn("<span class=aq-name>hill</span><span class=aq-xp>3 XP</span>", html)
        self.assertIn("1,200 XP", html)
        self.assertIn("Your last study session", html)
        self.assertNotIn("aki_winner.png", html)

    def test_server_and_deck_text_is_escaped(self):
        html = board.html(self.profile, None, 0, today=self.view())
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x>", html)
        self.assertNotIn("Spa<b>nish", html)
        self.assertIn("Spa&lt;b&gt;nish", html)

    def test_every_link_opens_a_known_page(self):
        html = board.html(self.profile, None, 2, today=self.view())
        pages = set(re.findall(r"ankiquest:web:(\w+)", html))
        self.assertTrue({"today", "history", "settings", "reminders", "inbox"} <= pages)
        for page in pages:
            self.assertIn(page, board.PAGES)
        self.assertEqual("/community#reminders", board.PAGES["reminders"])

    def test_missing_parts_are_left_out(self):
        html = board.html(None, None, 0, today=self.view(focus=None, goal=None, board=None, session=None, art=None, mood=None))
        self.assertIn("Your study starts with a deck.", html)
        self.assertNotIn("Today’s goal", html)
        self.assertNotIn("<select", html)
        self.assertNotIn("<img", html)
        done = dict(self.view()["focus"], status="done", label="Done today")
        self.assertNotIn("ankiquest:study", board.html(None, today=self.view(focus=done)))

    def test_a_closing_week_still_counting_shows_its_xp_and_close(self):
        # Just after the shared reset a Californian's Sunday still counts toward last week.
        closing = {"closing_week": {"xp": 1234, "ends_at": 10_000}}
        at = lambda ms: "04:00" if ms == 10_000 else "?"
        self.assertEqual(
            "Last week still counting: 1,234 XP · closes at 04:00",
            board.closing_week(closing, lambda value: value, 9_999, at),
        )
        self.assertIsNone(board.closing_week(closing, lambda value: value, 10_000, at))
        self.assertIsNone(board.closing_week({}, lambda value: value, 0, at))
        self.assertIsNone(board.closing_week({"closing_week": {"xp": 5, "ends_at": "soon"}}, lambda value: value, 0, at))
        self.assertIsNone(board.closing_week(None, lambda value: value, 0, at))
        spanish = board.closing_week(closing, lambda value: language.tr(value, "es"), 9_999, at)
        self.assertEqual("La semana pasada aún cuenta: 1,234 XP · cierra a las 04:00", spanish)

        live = dict(self.profile, closing_week={"xp": 50, "ends_at": int(time.time() * 1000) + 3_600_000})
        self.assertIn("aq-closing-week'>Last week still counting: 50 XP", board.html(live, 2, 0, today=self.view()))
        self.assertIn("Last week still counting: 50 XP", board.html(live, 2, 0))
        ended = dict(self.profile, closing_week={"xp": 50, "ends_at": 1})
        self.assertNotIn("Last week still counting", board.html(ended, 2, 0, today=self.view()))
        self.assertNotIn("Last week still counting", board.html(self.profile, 2, 0, today=self.view()))

    def test_all_quests_done_shows_the_winner(self):
        profile = {"quests": [{"title": "Combo", "progress": 5, "target": 5, "done": True, "reward": 15}]}
        self.assertIn("aki_winner.png", board.html(profile, today=self.view()))

    def test_meters_clamp_and_turn_full(self):
        self.assertIn("width:100%", board.meter(12, 10))
        self.assertIn("aq-full", board.meter(12, 10))
        self.assertIn("width:0%", board.meter(-3, 10))
        self.assertNotIn("aq-full", board.meter(0, 0))


class TranslationTests(unittest.TestCase):
    FILES = ("board.py", "goals.py", "today.py", "home.py", "today_ui.py", "moods.py", "goal_ui.py")

    def sources(self):
        found = set()
        for name in self.FILES:
            text = (ADDON / name).read_text("utf-8")
            for call in ast.walk(ast.parse(text)):
                if (
                    isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in ("tr", "translate")
                    and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)
                ):
                    found.add(call.args[0].value)
            if name in ("board.py", "today_ui.py"):
                found.update(re.findall(r'\(\s*[\w."]+,\s*"([^"]*[A-Za-z][^"]*)"\s*\)', text))
        found.update(moods.MESSAGES.values())
        found.update(moods.WAITING_LINES)
        found.add(moods.COMPANION_WELCOME)
        return found

    def test_every_today_string_has_a_spanish_translation(self):
        strings = self.sources()
        self.assertGreater(len(strings), 60)
        missing = sorted(text for text in strings if text not in language.SPANISH)
        self.assertEqual([], missing)

    def test_spanish_keeps_the_placeholders(self):
        for text in self.sources():
            self.assertEqual(re.findall(r"%[ds%]", text), re.findall(r"%[ds%]", language.SPANISH[text]), text)


class HomeTests(unittest.TestCase):
    """The glue in home.py, with Anki replaced by stand-ins."""

    def setUp(self):
        self.db = database()
        self.addCleanup(self.db.close)
        self.cutoff = int(__import__("time").time()) + 3600
        self.tree = node(0, children=[node(5, "Spanish", review=3)])
        self.settings = {"url": "https://example.test", "user": "hill", "token": "secret"}
        self.api = SimpleNamespace(
            configured=True, base="https://example.test", user="hill", name="hill", token="secret",
            leaderboard=Mock(return_value=[{"user": "hill", "display": "hill", "xp_total": 5, "periods": {"week": 5}}]),
            rank=Mock(return_value={"order": ["hill"]}), notifications=Mock(return_value=[]),
            profile=Mock(return_value={"level": 2, "streak": 1, "today": {"streak_minutes": 0, "reviews": 0}}),
            companion=Mock(return_value="ankilope"),
            deck_settings=Mock(return_value={}), server_info=Mock(return_value=(frozenset(), None)),
            _request=Mock(return_value={"items": [], "unread_count": 0, "action_count": 0}),
        )
        col = collection(self.db, self.tree, 100, self.cutoff)
        col.get_config = lambda *args: 4
        col.sched.counts = lambda: (0, 0, 3)
        col.startTimebox = Mock()
        col.decks = SimpleNamespace(
            all_names_and_ids=lambda include_filtered=False: [SimpleNamespace(id=5, name="Spanish")],
            get_current_id=lambda: 5, select=Mock(), get=lambda did, default=False: {"id": did} if did == 5 else None,
        )
        self.mw = SimpleNamespace(
            col=col,
            pm=SimpleNamespace(profile={}),
            taskman=SimpleNamespace(run_in_background=self.run_task),
            form=SimpleNamespace(menuTools=SimpleNamespace(addAction=Mock())),
            addonManager=SimpleNamespace(
                getConfig=lambda _: dict(self.settings), writeConfig=self.write_config,
                setWebExports=Mock(), addonFromModule=Mock(return_value="ankiquest"),
            ),
            progress=SimpleNamespace(timer=Mock()),
            deckBrowser=SimpleNamespace(refresh=Mock()),
            onOverview=Mock(), moveToState=Mock(),
            state="deckBrowser",
        )
        aqt = fake_anki(self, self.mw)
        self.addon = load_module("ankiquest_home_addon", "__init__.py", package=True)
        self.addon.client = lambda: self.api
        self.home = sys.modules["ankiquest_home_addon.home"]
        pictures = patch.object(self.home.board_pictures.share, "download_image", return_value=None)
        pictures.start()
        self.addCleanup(pictures.stop)
        from moment_fixture import cards
        self.cards = cards(self)
        self.hooks = aqt.gui_hooks

    def run_task(self, work, done, uses_collection=False):
        future = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        done(future)

    def render(self):
        content = SimpleNamespace(
            stats="", tree="<a class=deck href=# onclick=\"return pycmd('open:5')\">Spanish</a>",
        )
        deck_browser = SimpleNamespace(_dueTree=self.tree)
        for hook in self.hooks.deck_browser_will_render_content:
            hook(deck_browser, content)
        return content

    def review(self, at, seconds):
        self.db.execute("insert into revlog values (?, 1, 3, 1, ?)", (at, seconds * 1000))

    def test_the_deck_list_gets_the_today_panel_and_deck_badges(self):
        content = self.render()
        # A one-day streak not studied yet: Ankilope is sad.
        self.assertIn("/_addons/ankiquest/art/ankilope_sad.png", content.stats)
        self.assertIn("pycmd('ankiquest:study:5')", content.stats)
        self.assertIn("Today’s goal", content.stats)
        self.assertIn("Change goal", content.stats)
        self.assertIn("aq-player aq-me", content.stats)
        self.assertIn("ankiquest-review-now", content.tree)
        self.settings["deck_status"] = False
        self.home.local["days"] = None
        self.assertNotIn("ankiquest-day", self.render().tree)

    def test_a_streak_without_study_today_makes_aki_sad(self):
        # Regression: cards due and no study today showed the review pose, not a worried Aki.
        self.api.companion.return_value = "aki"
        self.addon.state.update(companion="aki", companion_account=None)
        self.served_today()
        self.addon.state["profile"]["streak"] = 64
        self.home.local["days"] = None
        content = self.render()
        self.assertIn("/_addons/ankiquest/art/aki_sad.png", content.stats)
        self.assertNotIn("art/aki_review.png", content.stats)

    def test_a_waiting_streak_says_so_before_the_decks(self):
        # Regression (#301): cards due and no study today said "A small step starts with one card.";
        # Android's Home card says the streak is waiting.
        self.addon.state.update(companion="aki", companion_account=None)
        self.served_today()
        self.addon.state["profile"]["streak"] = 64
        content = self.render()
        self.assertIn("You haven’t studied today. Your 64-day streak is still waiting.", content.stats)
        self.assertNotIn("A small step starts with one card.", content.stats)

    def test_a_one_day_streak_waits_in_the_singular(self):
        self.addon.state.update(companion="aki", companion_account=None)
        self.served_today()
        self.assertIn("You haven’t studied today. Your 1-day streak is still waiting.", self.render().stats)

    def test_frozen_days_before_today_bring_the_freeze_message(self):
        # Regression (#301): a freeze kept yesterday, today is pending, and cards are due. The
        # freeze message only followed a protected day; Android's Home card follows the frozen mood.
        self.addon.state.update(companion="aki", companion_account=None)
        self.served_today()
        self.addon.state["profile"].update(streak=5, heatmap=[{"frozen": True}, {"frozen": False}])
        content = self.render()
        self.assertIn("Your streak is protected by a freeze. A fresh start is waiting.", content.stats)
        self.assertNotIn("A small step starts with one card.", content.stats)

    def test_cards_due_bring_no_greeting(self):
        # Regression: "A small step starts with one card." said nothing useful above the deck.
        self.api.companion.return_value = "aki"
        self.addon.state.update(companion="aki", companion_account=None)
        self.served_today()
        self.addon.state["profile"]["streak"] = 0
        content = self.render()
        self.assertIn("pycmd('ankiquest:study:5')", content.stats)
        self.assertIn("/_addons/ankiquest/art/aki_", content.stats)
        self.assertNotIn("small step", content.stats)
        self.assertNotIn("class=aq-bubble", content.stats)

    def test_studying_and_period_links_act_only_from_the_deck_list(self):
        handle = self.hooks.webview_did_receive_js_message[-1]
        self.assertEqual((True, None), handle(False, "ankiquest:study:5", self.mw.deckBrowser))
        self.mw.col.decks.select.assert_called_once_with(5)
        self.mw.onOverview.assert_called_once_with()
        handle(False, "ankiquest:period:month", self.mw.deckBrowser)
        self.assertEqual("month", self.mw.pm.profile[self.home.board_data._OLD_PERIOD])
        self.assertFalse(handle(False, "ankiquest:period:day", object()))
        self.assertEqual("month", self.mw.pm.profile[self.home.board_data._OLD_PERIOD])

    def session(self, reviews):
        self.mw.state = "review"
        for hook in self.hooks.state_did_change:
            hook("review", "overview")
        self.home.local["session"]["started"] -= 60_000
        started = self.home.local["session"]["started"]
        for index in range(reviews):
            self.review(started + index + 1, 30)
        self.mw.state = "overview"
        for hook in self.hooks.state_did_change:
            hook("overview", "review")

    def served_today(self, streak_minutes=0, **today):
        """The last profile, from before this test's reviews: today began at the day's cutoff."""
        self.addon.state["profile"] = {
            "user": "hill", "streak": 1, "streak_state": "pending", "day_ends_at": self.cutoff * 1000,
            "last_review_id": 0,
            "today": dict({"starts_at": (self.cutoff - 86_400) * 1000, "reviews": 0, "time_ms": 0, "minutes": 0,
                           "streak_minutes": streak_minutes}, **today),
        }

    def test_session_keeps_started_deck(self):
        self.served_today()
        self.mw.col.decks.current = Mock(return_value={"id": 5, "name": "Spanish", "dyn": 0})
        self.mw.state = "review"
        for hook in self.hooks.state_did_change:
            hook("review", "overview")
        self.home.local["session"]["started"] -= 60_000
        self.review(self.home.local["session"]["started"] + 1, 30)
        self.mw.col.decks.current.return_value = {"id": 6, "name": "French", "dyn": 0}
        self.mw.state = "overview"
        for hook in self.hooks.state_did_change:
            hook("overview", "review")
        expected = {"id": "5", "path": "Spanish"}
        self.assertEqual(expected, self.mw.pm.profile[self.home.SESSION_KEY]["deck"])
        self.assertEqual(expected, self.addon._moments._card._summary["deck"])
        self.assertEqual(expected, self.addon._moments._completion._summary["deck"])

    def test_deck_prompt_with_recaps_off(self):
        self.settings.update(session_summary=False, goal_celebrations=False)
        self.mw.col.decks.current = Mock(return_value={"id": 5, "name": "Spanish", "dyn": 0})
        self.session(2)
        self.assertIsNone(self.addon._moments._card)
        prompt = self.addon._moments._completion
        self.assertEqual({"id": "5", "path": "Spanish"}, prompt._summary["deck"])
        prompt._start.assert_called_once_with()

    def test_the_first_session_of_the_day_celebrates_then_later_ones_recap(self):
        self.remember("cards", 100)
        self.served_today()
        self.session(2)
        card = self.addon._moments._card
        self.assertEqual("Streak minimum reached — syncing", card._items[0]["title"])
        self.assertIn("once your reviews upload", card._items[0]["body"])
        self.assertEqual(2, card._summary["reviews"])
        self.assertEqual("aki_streak", self.addon.moments._pose(card._items[0], "aki"))
        card._dialog.close()
        self.session(1)
        card = self.addon._moments._card
        self.assertEqual("Your study session", card._items[0]["title"])
        card._dialog.close()
        self.addon.save_config({"session_summary": False})
        self.assertFalse(self.settings["session_summary"])
        self.session(1)
        self.assertEqual(2, self.cards.call_count)
        self.assertEqual(3, self.mw.pm.profile[self.home.SESSION_KEY]["remaining"])

    def test_the_streak_is_not_celebrated_without_the_servers_word(self):
        self.remember("cards", 100)
        self.session(2)
        self.assertEqual("Your study session", self.addon._moments._card._items[0]["title"])

    def test_unsent_reviews_short_of_the_servers_minimum_do_not_secure_the_streak(self):
        self.remember("cards", 100)
        self.served_today(streak_minutes=5, reviews=1, time_ms=180_000, minutes=3)
        self.session(2)
        self.assertEqual("Your study session", self.addon._moments._card._items[0]["title"])
        self.served_today(streak_minutes=5, reviews=1, time_ms=240_000, minutes=4)
        self.home.local["days"] = None
        goal = self.home.goal_status()
        self.assertTrue(goal.minimum_done and goal.minimum_waiting)
        self.assertEqual(5, goal.minimum_minutes)

    def test_the_goal_popup_is_left_to_a_server_with_wins(self):
        self.remember("cards", 1)
        self.served_today()
        self.api.server_info = Mock(return_value=(frozenset({"wins"}), None))
        self.session(2)
        item = self.addon._moments._card._items[0]
        self.assertEqual("Streak minimum reached — syncing", item["title"])
        self.assertNotIn("goal", item["body"].lower())
        self.api.server_info.assert_called_once_with()

    def test_an_older_server_without_wins_keeps_the_goal_popup(self):
        self.remember("cards", 1)
        self.api.server_info = Mock(return_value=(frozenset(), None))
        self.home.load_capabilities(self.api)
        self.session(2)
        self.assertEqual("Daily goal reached! 🎉", self.addon._moments._card._items[0]["title"])

    def moving_to(self, main, works=True):
        """Loads capabilities naming `main`, with the token working there when `works`."""
        self.api.language = "en"
        self.api.server_info = Mock(return_value=(frozenset({"wins"}), main))
        there = SimpleNamespace(base=main.rstrip("/") if main else main, devices=Mock())
        if not works:
            there.devices.side_effect = OSError("unauthorized")
        self.home.Client = Mock(return_value=there)
        self.addon.client = lambda: self.addon.Client(
            self.settings["url"], self.settings["user"], self.settings["token"], "en")
        self.mw.pm.profile[self.home.SESSION_KEY] = {"account": ["https://example.test", "hill"], "reviews": 2}
        self.settings[self.home.SETUP_SHOWN] = ["https://example.test hill"]
        self.home.local["capabilities"] = None
        self.home.load_capabilities(self.api)
        return there

    def test_a_player_moves_to_the_main_address_once_the_token_works_there(self):
        self.remember("cards", 1)
        there = self.moving_to("https://anki.example.test")
        self.home.Client.assert_called_once_with("https://anki.example.test", "hill", "secret", "en")
        there.devices.assert_called_once_with()
        self.assertEqual("https://anki.example.test", self.settings["url"])
        self.assertEqual(["https://anki.example.test", "hill"], self.mw.pm.profile[self.home.PLAN_KEY]["account"])
        self.assertEqual(["https://anki.example.test", "hill"], self.mw.pm.profile[self.home.SESSION_KEY]["account"])
        self.assertEqual(["https://anki.example.test hill"], self.settings[self.home.SETUP_SHOWN])

    def test_a_player_stays_when_the_token_fails_at_the_main_address(self):
        self.moving_to("https://anki.example.test", works=False)
        self.assertEqual("https://example.test", self.settings["url"])
        self.assertEqual(["https://example.test", "hill"], self.mw.pm.profile[self.home.SESSION_KEY]["account"])

    def test_a_player_stays_at_the_same_or_a_plain_http_address(self):
        for main in ("https://example.test", "https://example.test/", "http://anki.example.test", None):
            self.moving_to(main)
            self.home.Client.assert_not_called()
            self.assertEqual("https://example.test", self.settings["url"])

    def write_config(self, _, values):
        self.settings = dict(values)

    def test_an_unconnected_profile_gets_one_sign_in_offer(self):
        self.settings.update(url="", user="", token="")
        self.addon.QTimer = SimpleNamespace(singleShot=lambda delay, callback: callback())
        # Aki greeted on this computer before; test_addon_greeting covers the first open.
        self.mw.pm.meta = {self.addon.greeting.KEY: self.addon.greeting.State.SHOWN.value}
        self.addon.QApplication = SimpleNamespace(activeModalWidget=lambda: None)
        self.addon.ask_account = Mock(return_value=None)
        for name in ("refresh_shared_decks", "refresh", "poll", "maybe_check_updates"):
            setattr(self.addon, name, Mock())

        self.addon.on_profile_open()
        self.addon.on_profile_open()
        self.addon.ask_account.assert_called_once_with("", dismiss="Not now")

        self.mw.pm.profile = {}
        self.addon.on_profile_open()
        self.assertEqual(2, self.addon.ask_account.call_count)

    def test_a_revoked_poll_token_offers_sign_in_without_retrying_on_render(self):
        self.api.rank.side_effect = self.addon.ServerError(HTTPStatus.UNAUTHORIZED, "revoked")
        self.addon.poll(quiet=True)

        self.assertIn("Sign in to AnkiQuest again", self.render().stats)
        self.api.rank.assert_called_once()

        self.api.token = "new-token"
        self.api.rank.side_effect = None
        self.assertNotIn("Sign in to AnkiQuest again", self.render().stats)
        self.assertEqual(2, self.api.rank.call_count)

    def test_account_management_opens_the_saved_server_without_credentials(self):
        self.addon.ui.settings_dialog = Mock(return_value=None)
        self.addon.open_settings()
        manage = self.addon.ui.settings_dialog.call_args.kwargs["on_manage"]
        manage()
        self.addon.openLink.assert_called_once_with("https://example.test/settings")

        self.api.base = "https://member:password@example.test"
        manage()
        self.addon.openLink.assert_called_once()

    def remember(self, mode="cards", value=100, since=None, chosen=True):
        since = self.home.server_day() if since is None else since
        self.mw.pm.profile[self.home.PLAN_KEY] = {
            "account": ["https://example.test", "hill"], "mode": mode, "value": value, "since": since, "chosen": chosen,
        }

    def serve(self, goal):
        """Answers like the server's goal routes and records what was asked."""
        calls = []

        def request(path, body=None, method=None):
            calls.append((path, body, method))
            if path.endswith("/reached"):
                raise ValueError("Expecting value")
            if method == "PUT":
                return {"mode": body["mode"], "value": body.get("value"), "since": 20000, "chosen": True}
            return goal

        self.api._request = request
        self.home.goal_ui = SimpleNamespace(goal_dialog=Mock(return_value=None))
        return calls

    def test_an_older_goal_moves_to_the_server_once_and_needs_no_setup(self):
        self.settings.update(goal_mode="cards", goal_cards=80, goal_backlog_percent=10, goal_minutes=20)
        calls = self.serve({"mode": "backlog", "value": 30, "since": 20000, "chosen": False})
        self.home.sync_goal(prompt=True)
        self.assertEqual(("/api/goal/hill", {"mode": "cards", "value": 80}, "PUT"), calls[-1])
        self.assertFalse(set(self.settings) & set(self.home.goals.LEGACY_KEYS))
        self.home.goal_ui.goal_dialog.assert_not_called()
        self.assertEqual("cards", self.mw.pm.profile[self.home.PLAN_KEY]["mode"])
        self.home.sync_goal(prompt=True)
        self.assertEqual(1, sum(1 for call in calls if call[2] == "PUT"))

    def test_the_goal_dialog_opens_by_itself_once_per_account_while_no_goal_is_chosen(self):
        calls = self.serve({"mode": "backlog", "value": 30, "since": 20000, "chosen": False})
        self.home.goal_ui.goal_dialog.return_value = ("backlog", 14)
        self.home.sync_goal(prompt=True)
        self.home.goal_ui.goal_dialog.assert_called_once()
        self.assertEqual(("/api/goal/hill", {"mode": "backlog", "value": 14}, "PUT"), calls[-1])
        self.assertEqual(["https://example.test hill"], self.settings["goal_setup_shown"])
        self.home.sync_goal(prompt=True)
        self.home.goal_ui.goal_dialog.assert_called_once()
        self.home.sync_goal(prompt=False)
        self.home.goal_ui.goal_dialog.assert_called_once()

    def test_goal_setup_joins_a_pending_silent_read(self):
        calls = self.serve({"mode": "backlog", "value": 30, "since": 20000, "chosen": False})
        tasks = []
        self.mw.taskman.run_in_background = lambda work, done: tasks.append((work, done))
        self.home.sync_goal()
        self.home.sync_goal(prompt=True)
        self.assertEqual(1, len(tasks))
        self.run_task(*tasks.pop())
        self.assertEqual(1, len(calls))
        self.home.goal_ui.goal_dialog.assert_called_once()

    def test_board_renders_back_off_after_a_failed_fetch(self):
        self.api.leaderboard.side_effect = OSError("offline")
        clock = 100
        self.home.time = SimpleNamespace(time=self.home.time.time, monotonic=lambda: clock)
        for _ in range(3):
            self.home.board_view(self.api)
        self.api.leaderboard.assert_called_once()

        clock += self.home.BOARD_RETRY_MS / 1000
        self.api.leaderboard.side_effect = None
        board = self.home.board_view(self.api)
        self.assertEqual(2, self.api.leaderboard.call_count)
        self.assertEqual("week", board["period"])

    def test_board_wait_doubles_after_consecutive_failures(self):
        self.api.leaderboard.side_effect = OSError("offline")
        clock = 100
        self.home.time = SimpleNamespace(time=self.home.time.time, monotonic=lambda: clock)
        self.home.board_view(self.api)
        clock += 30
        self.home.board_view(self.api)
        self.assertEqual(2, self.api.leaderboard.call_count)
        clock += 30
        self.home.board_view(self.api)
        self.assertEqual(2, self.api.leaderboard.call_count)
        clock += 30
        self.api.leaderboard.side_effect = None
        self.home.board_view(self.api)
        self.assertEqual(3, self.api.leaderboard.call_count)

    def test_the_deck_list_can_retry_a_failed_board_now(self):
        self.api.leaderboard.side_effect = OSError("offline")
        rendered = self.render().stats
        self.assertIn("The leaderboard could not be loaded.", rendered)
        self.assertIn("ankiquest:retry-board", rendered)
        self.api.leaderboard.side_effect = None

        result = self.home.on_js_message(False, "ankiquest:retry-board", self.mw.deckBrowser)
        self.assertEqual((True, None), result)
        self.assertEqual(2, self.api.leaderboard.call_count)
        self.assertIn("aq-player aq-me", self.render().stats)

    def test_a_dismissed_setup_counts_as_shown_and_a_chosen_goal_needs_none(self):
        self.serve({"mode": "backlog", "value": 30, "since": 20000, "chosen": True})
        self.home.sync_goal(prompt=True)
        self.home.goal_ui.goal_dialog.assert_not_called()
        calls = self.serve({"mode": "backlog", "value": 30, "since": 20000, "chosen": False})
        self.home.sync_goal(prompt=True)
        self.home.sync_goal(prompt=True)
        self.home.goal_ui.goal_dialog.assert_called_once()
        self.assertFalse([call for call in calls if call[2] == "PUT"])

    def test_the_panels_goal_button_opens_the_dialog(self):
        calls = self.serve({})
        self.assertIn("pycmd('ankiquest:goal')", self.render().stats)
        handle = self.hooks.webview_did_receive_js_message[-1]
        self.assertEqual((True, None), handle(False, "ankiquest:goal", self.mw.deckBrowser))
        chosen = self.home.goal_ui.goal_dialog.call_args.args[1]
        self.assertEqual("backlog", chosen.mode)
        self.assertFalse([call for call in calls if call[2] == "PUT"])

    def test_a_reached_backlog_goal_is_reported_once_a_day(self):
        calls = self.serve({})
        self.remember("backlog", 30)
        self.review(int(__import__("time").time() * 1000), 30)
        self.render()
        self.render()
        reached = [call for call in calls if call[0].endswith("/reached")]
        self.assertEqual([("/api/goal/hill/reached", {"day": self.home.server_day()}, None)], reached)

    def test_a_backlog_plan_that_ran_out_restarts_once(self):
        calls = self.serve({})
        self.remember("backlog", 7, since=self.home.server_day() - 7)
        self.render()
        self.render()
        self.assertEqual([("/api/goal/hill", {"mode": "backlog", "value": 7, "restart": True}, "PUT")], [call for call in calls if call[2] == "PUT"])
        self.assertEqual(20000, self.mw.pm.profile[self.home.PLAN_KEY]["since"])


if __name__ == "__main__":
    unittest.main()
