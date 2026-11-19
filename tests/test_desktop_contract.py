"""Recorded server responses must survive the real desktop client and consumers."""
from http import HTTPStatus
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from addon_loader import load_in_package

client, verdict, goals, boards, activity, inbox, share, conquests, notify = (
    load_in_package("desktop_contract", name) for name in (
        "client", "day_verdict", "goals", "board_data", "activity", "inbox", "share", "conquests", "notify"
    )
)
EXAMPLES = Path(__file__).resolve().parents[1] / "docs/api/examples"
moment_share = load_in_package("desktop_contract", "moment_share")


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text("utf-8"))


class Contracts(unittest.TestCase):
    def setUp(self):
        self.api = client.Client("https://quest.test", "hill", "example-token", "de")
        self.routes, self.sent, self.headers = {}, [], {}
        transport = patch.object(client, "open_url", side_effect=self.response)
        transport.start()
        self.addCleanup(transport.stop)

    def response(self, url, data=None, headers=None, method=None, timeout=20):
        path = urlsplit(url).path
        query = urlsplit(url).query
        route = path + ("?" + query if query else "")
        verb = method or ("POST" if data is not None else "GET")
        self.sent.append((verb, route, json.loads(data) if data is not None else None))
        if path != "/api/capabilities":
            self.assertEqual("Bearer example-token", headers["Authorization"])
            self.assertEqual("de", headers["Accept-Language"])
        response = BytesIO((EXAMPLES / (self.routes[verb, route] + ".json")).read_bytes())
        response.status = HTTPStatus.OK
        response.headers = self.headers
        return response

    def test_profile_and_upload_produce_the_same_confirmed_day(self):
        self.routes = {("GET", "/api/profile/hill"): "profile", ("POST", "/api/reviews/hill"): "upload"}
        profile = self.api.profile()
        uploaded = self.api.upload([], 4, True, deleted=[123], clock_offset=-60)
        for answer, expected_days in ((profile, 14), (uploaded, 30)):
            with self.subTest(response=answer.get("feedback", "profile")):
                day = verdict.verdict(answer, [], answer["today"]["starts_at"] + 1)
                self.assertTrue(day["met"])
                self.assertFalse(day["waiting"])
                self.assertEqual(5, day["reviews"])
                self.assertEqual(1793182204000, answer["last_review_id"])
                plan = goals.plan(answer["goal"], 20754)
                self.assertEqual((goals.BACKLOG, expected_days, 20754), (plan.mode, plan.value, plan.since))
        self.assertIsNone(notify.feedback(uploaded, True))
        self.assertEqual({"reviews": [], "silent": True, "deleted": [123],
                          "clock": {"offset_west_min": -60, "rollover_hour": 4}}, self.sent[-1][2])

    def test_rank_words_use_the_players_voice_when_shared(self):
        self.routes = {("POST", "/api/rank/hill"): "rank"}
        answer = self.api.rank(["cerro", "hill"], 1792987200000)
        place = answer["order"].index("hill") + 1
        win = share.win_from_place(answer["change"], place)
        self.assertEqual("I passed Cerro.", win["body"])
        self.assertEqual({"place": 1}, share.request_body(win))
        self.assertEqual({"previous": ["cerro", "hill"], "week": 1792987200000}, self.sent[-1][2])

    def test_each_recorded_board_keeps_ranks_and_private_summary_rows(self):
        cases = (("leaderboard", "week", "friends", "hill", 101),
                 ("leaderboard_day", "day", "friends", "hill", 101),
                 ("leaderboard_global", "day", "global", "hill", 107),
                 ("leaderboard_global_hidden", "week", "global", "ana", 246))
        for name, period, scope, player, first_xp in cases:
            with self.subTest(example=name):
                self.routes = {("GET", "/api/leaderboard?period=%s&scope=%s" % (period, scope)): name}
                rows = self.api.leaderboard(period, scope)
                found = boards._Board(boards._Query(period, scope), rows, [], False)
                ranked = boards._rows(found, player)
                self.assertEqual(first_xp, ranked[0][1]["xp"])
                self.assertTrue(any(mine for _, _, mine in ranked))
                if scope == "global":
                    stranger = next(row for _, row, mine in ranked if not mine)
                    self.assertNotIn("today_reviews", stranger)
                    self.assertNotIn("streak_state", stranger)

    def test_a_player_who_never_uploaded_learns_why_the_board_and_feed_are_empty(self):
        self.api.name = self.api.user = "newcomer"
        self.routes = {("GET", "/api/leaderboard?period=week&scope=friends"): "leaderboard_locked",
                       ("GET", "/api/activity/newcomer?limit=50"): "activity_locked"}
        self.headers = {"X-Ankiquest-Locked": "upload_first"}
        rows = self.api.leaderboard("week", "friends")
        self.assertEqual([], rows)
        self.assertEqual("upload_first", rows.locked)
        page = activity._load(self.api)
        self.assertEqual([], page.items)
        self.assertEqual("upload_first", page.locked)

    def test_answers_without_the_lock_header_are_not_locked(self):
        self.routes = {("GET", "/api/leaderboard?period=week&scope=friends"): "leaderboard"}
        self.assertIsNone(getattr(self.api.leaderboard("week", "friends"), "locked", None))
        self.routes = {("GET", "/api/activity/hill?limit=50"): "activity"}
        self.assertIsNone(activity._load(self.api).locked)

    def test_activity_keeps_actions_and_notices_keep_share_ids(self):
        self.routes = {("GET", "/api/activity/hill?limit=50"): "activity"}
        page = activity._load(self.api)
        self.assertEqual((7, 1, 15), (page.unread, page.actions, page.before))
        self.assertEqual(4, inbox.challenge_target(page.attention[0]))
        self.assertFalse(inbox.answerable(page.attention[0]))
        # Notification rows, as activity items carry them.
        notices = example("notifications")
        level = next(row for row in notices if row.get("topic") == "level")
        self.assertTrue(inbox.shareable(level))
        self.assertEqual("I reached level 3 with 400 XP.", share.win_from_entry(level)["body"])
        wins = {row["id"]: row for row in example("wins")["wins"]}
        for row in notices:
            if inbox.shareable(row):
                win = share.win_from_entry(row)
                self.assertIn(win["win"], wins)
                self.assertEqual(row["moment"], wins[win["win"]]["key"])
                self.assertEqual({"win": win["win"], "to": "friends"}, share.request_body(win))
                self.assertTrue(share.card_url(self.api, win).endswith("/%d/card.png" % win["win"]))

    def test_private_hide_returns_the_recorded_hidden_people(self):
        path = "/api/leaderboard/hidden/hill"
        self.routes = {("GET", path): "leaderboard_hide", ("POST", path): "leaderboard_hide"}
        saved = boards._hide(self.api, boards._Visibility.HIDDEN, "ana")
        self.assertEqual([{"display": "Ana", "user": "ana"}], saved)
        self.assertEqual({"action": "hide", "user": "ana"}, self.sent[-1][2])
        self.assertEqual(saved, boards._hidden(self.api))

    def test_goal_decks_and_capabilities_enable_the_expected_controls(self):
        self.routes = {("GET", "/api/goal/hill"): "goal", ("GET", "/api/decks/hill"): "decks",
                       ("GET", "/api/capabilities"): "capabilities"}
        plan = goals.plan(goals.fetch(self.api), 20754)
        self.assertTrue(plan.chosen)
        self.assertEqual(goals.Plan(goals.BACKLOG, 14, 20754, True), plan)
        settings = self.api.deck_settings()
        self.assertTrue(settings["global_leaderboard"])
        self.assertEqual(["cerro", "friend"], [person["user"] for person in settings["recipients"]])
        self.assertEqual([], self.api.shared_decks())
        features, address = self.api.server_info()
        self.assertTrue({"activity", "wins", "global_leaderboard_hide"}.issubset(features))
        self.assertEqual("https://anki.example.test", address)

    def test_conquest_label_stats_tell_and_undo_match_the_server(self):
        at = 1793097000000
        path = "/api/conquests/hill/%d" % at
        self.routes = {("GET", path): "conquest", ("POST", path + "/tell"): "conquest_tell",
                       ("DELETE", path + "/tell"): "conquest_untell"}
        found = conquests._load(self.api, at)
        self.assertEqual("4 lapses · 11 answers · 10 days to learn", conquests._stats(found, str))
        win = conquests._win(self.api, at, found, "Spanish", str)
        self.assertIn("I finally learned “el murciélago”, a card I had forgotten 4 times.", win["body"])
        self.assertIn("From my deck “Spanish”.", win["body"])
        self.assertEqual(6, win["win"])
        self.assertFalse(conquests._can_undo(found, 0))
        self.assertEqual({"told": 0}, conquests._tell(self.api, at))
        self.assertEqual({"retracted": 0}, conquests._undo(self.api, at))

    def test_moment_recipients_and_send_specific_undo_use_recorded_contracts(self):
        self.routes = {("GET", "/api/capabilities"): "capabilities", ("GET", "/api/social/hill"): "social",
                       ("POST", "/api/share/hill"): "share_moment",
                       ("DELETE", "/api/share/hill/6?until=1793269800000"): "share_undo_send"}
        win = {"win": 6, "title": "Anki-tan unlocked", "body": "A 66-day streak.", "kind": "companion_unlocked"}
        targets = moment_share._load(self.api, win, [])
        self.assertEqual(["user:friend", "group:2", "group:1"], [target._key for target in targets])
        picked = moment_share._Picked((targets[0], targets[1]))
        receipt = moment_share._send(self.api, win, picked, "  A\nsmall win ")
        self.assertEqual({"moment": {"win": 6}, "to": {"friends": ["friend"], "groups": [2]}, "note": "A small win"}, self.sent[-1][2])
        self.assertEqual(1, moment_share._retract(self.api, receipt))

    def test_conquest_share_uses_its_review_id_and_no_automatic_publication(self):
        self.routes = {("POST", "/api/share/hill"): "share_moment_group"}
        moment_share._send(self.api, {"conquest": 1793097000000}, moment_share._Choice.CIRCLE, "")
        self.assertEqual([("POST", "/api/share/hill", {"moment": {"conquest": 1793097000000}, "to": "circle"})], self.sent)


if __name__ == "__main__":
    unittest.main()
