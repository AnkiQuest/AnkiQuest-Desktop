"""The social choices behind the Friends window: invitation codes, goal actions and draft
creation (social_data), the sections the Progress window reads (progress_data), and the
labels the goal page writes (friend_goals_ui)."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from addon_loader import fake_anki, load_in_package

social = load_in_package("aq_social_data_test", "social_data")
progress = load_in_package("aq_progress_data_test", "progress_data")


class InviteCode(unittest.TestCase):
    def test_a_bare_code_is_taken_as_it_is(self):
        self.assertEqual("abc-123", social._invite_code("  abc-123 \n", "https://quest.example"))
        self.assertEqual(social._invite_code("_x", "https://quest.example").strip(), "_x")

    def test_a_link_of_the_same_server_yields_its_code(self):
        base = "https://quest.example"
        self.assertEqual("abc123", social._invite_code("https://quest.example/join/abc123", base))
        self.assertEqual("abc123", social._invite_code("https://quest.example/join/abc123/", base))

    def test_another_servers_link_is_refused(self):
        with self.assertRaises(ValueError):
            social._invite_code("https://elsewhere.test/join/abc123", "https://quest.example")

    def test_anything_else_is_refused(self):
        for text in ("", "a b", "../config", "join/abc", "x" * 129):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    social._invite_code(text, "https://quest.example")


class GoalState(unittest.TestCase):
    def test_a_known_status_is_its_state_and_an_unknown_one_is_unknown(self):
        self.assertIs(social._GoalState.ACTIVE, social._state({"status": "active"}))
        self.assertIs(social._GoalState.UNKNOWN, social._state({"status": "surprise"}))
        self.assertIs(social._GoalState.UNKNOWN, social._state({}))


class GoalActions(unittest.TestCase):
    def test_an_invited_member_may_accept_or_decline(self):
        goal = {"status": "active", "end_at": 2000, "members": [{"user": "hill", "status": "invited"}]}
        self.assertEqual((social._GoalAction.ACCEPT, social._GoalAction.DECLINE), social._actions(goal, "hill", 1000))

    def test_an_accepted_member_leaves_only_when_not_the_creator(self):
        goal = {"status": "active", "end_at": 2000, "creator": "cerro", "members": [{"user": "hill", "status": "accepted"}]}
        self.assertEqual((social._GoalAction.LEAVE,), social._actions(goal, "hill", 1000))
        self.assertEqual((social._GoalAction.CANCEL,), social._actions(dict(goal, creator="hill"), "hill", 1000))

    def test_an_ended_goal_member_of_any_kind_has_no_action(self):
        for status in ("ended", "cancelled", "declined", "unknown"):
            with self.subTest(status=status):
                goal = {"status": status, "end_at": 2000, "members": [], "creator": "hill"}
                self.assertEqual((), social._actions(goal, "hill", 1000))
        self.assertEqual((), social._actions({"status": "active", "members": []}, "hill", 1000))

    def test_a_past_goal_end_has_no_action_even_while_active(self):
        goal = {"status": "active", "members": [{"user": "hill", "status": "accepted"}], "end_at": 999}
        self.assertEqual((), social._actions(goal, "hill", 1000))
        self.assertIsNotNone(social._actions(dict(goal, end_at=1000), "hill", 1000))


class WeeklySuggestion(unittest.TestCase):
    def test_a_fresh_undismissed_suggestion_without_a_challenge_is_kept(self):
        data = {"weekly_suggestion": {"dismissed": False, "challenge_id": None, "expires_at": 2000}}
        self.assertEqual(data["weekly_suggestion"], social._suggestion(data, now=1000))

    def test_dismissed_or_expired_or_accepted_suggestions_are_none(self):
        fresh = {"dismissed": False, "challenge_id": None, "expires_at": 2000}
        for name, data in (
            ("dismissed", {"weekly_suggestion": dict(fresh, dismissed=True)}),
            ("expired", {"weekly_suggestion": dict(fresh, expires_at=999)}),
            ("accepted", {"weekly_suggestion": dict(fresh, challenge_id=6)}),
            ("missing", {}),
            ("null", {"weekly_suggestion": None}),
        ):
            with self.subTest(name=name):
                self.assertIsNone(social._suggestion(data, now=1000))


class Draft(unittest.TestCase):
    def test_the_same_body_keeps_its_request_id_and_a_new_one_gets_another(self):
        draft = social._Draft()
        body = {"title": " Spanish ", "recipients": ["cerro", "hill", "cerro"], "kind": "study_days"}
        first = draft._body(body)
        self.assertEqual("Spanish", first["title"])
        self.assertEqual(["cerro", "hill"], first["recipients"])
        again = draft._body(dict(body, recipients=["hill", "cerro", "hill"]))
        self.assertEqual(first["request_id"], again["request_id"], "an unchanged draft retries the same id")
        third = draft._body(dict(body, title=" Portuguese "))
        self.assertNotEqual(first["request_id"], third["request_id"], "a changed draft starts a new id")


class ProgressSections(unittest.TestCase):
    def test_records_reads_the_records_and_history_reads_the_years(self):
        api = SimpleNamespace(user="hill", _request=Mock(return_value={}))
        progress._fetch(api, progress._Section.RECORDS)
        api._request.assert_called_once_with("/api/records")
        progress._fetch(api, progress._Section.HISTORY, 2026)
        api._request.assert_called_with("/api/study/hill?year=2026")
        progress._fetch(api, progress._Section.HISTORY)
        api._request.assert_called_with("/api/study/hill")


class GoalLabels(unittest.TestCase):
    def setUp(self):
        fake_anki(self, SimpleNamespace())
        self.goals = load_in_package("aq_friend_goals_ui_test", "friend_goals_ui")

    def test_every_goal_state_and_action_has_its_label(self):
        for state in self.goals.social_data._GoalState:
            with self.subTest(state=state):
                self.assertIn(state, self.goals._STATES, state)
        for action in self.goals.social_data._GoalAction:
            with self.subTest(action=action):
                self.assertIn(action, self.goals._ACTIONS, action)


if __name__ == "__main__":
    unittest.main()
