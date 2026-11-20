"""The Today panel and its warning must use the same verdict as the goal meter."""

import time
import unittest

import test_desktop_today as fixture


class DayState(unittest.TestCase):
    setUp = fixture.HomeTests.setUp
    run_task = fixture.HomeTests.run_task
    write_config = fixture.HomeTests.write_config
    render = fixture.HomeTests.render
    review = fixture.HomeTests.review
    served_today = fixture.HomeTests.served_today
    remember = fixture.HomeTests.remember

    def pending_day(self):
        self.remember("cards", 100)
        self.served_today(streak_minutes=5, reviews=1, time_ms=240_000, minutes=4)
        self.addon.state["profile"].update(
            streak=7, at_risk=True, streak_warning={"title": "Your streak is at risk", "body": "Study today"},
        )
        self.tree = fixture.node(0, children=[fixture.node(5, "Spanish")])

    def test_unsent_reviews_update_the_pill_mood_and_warning_together(self):
        self.pending_day()
        self.review(int(time.time() * 1000) - 1, 60)
        html = self.render().stats
        self.assertIn("8 day streak", html)
        self.assertIn("Syncing", html)
        self.assertNotIn("streak at risk today", html)
        self.assertIn("aki_streak_hot.png", html, "today counts on an 8-day streak")
        self.assertEqual(7, self.addon.state["profile"]["streak"], "rendering does not rewrite the server cache")
        self.assertEqual(1, self.addon.state["profile"]["today"]["reviews"])
        self.addon.tooltip.reset_mock()
        self.addon.announce({}, self.addon.state["profile"], [], False)
        self.addon.tooltip.assert_not_called()

    def test_an_earlier_unsent_day_hides_the_streak_length(self):
        self.pending_day()
        starts = self.addon.state["profile"]["today"]["starts_at"]
        self.review(starts - 1, 60)
        html = self.render().stats
        self.assertNotIn("7 day streak", html)
        self.assertIn("Streak unknown", html)

    def test_only_the_servers_confirmed_day_is_called_secured(self):
        self.pending_day()
        self.addon.state["profile"].update(streak_state="studied")
        html = self.render().stats
        self.assertIn("7 day streak", html)
        self.assertIn("Streak secured", html)
        self.assertNotIn("Syncing", html)
        self.assertNotIn("streak at risk today", html)

    def test_the_own_today_board_row_does_not_reuse_yesterdays_xp(self):
        self.pending_day()
        self.addon.state["profile"]["day_ends_at"] = int(time.time() * 1000) - 1
        self.mw.pm.profile[self.home.board_data._OLD_PERIOD] = "day"
        self.api.leaderboard.return_value = [{"user": "hill", "display": "hill", "periods": {"day": 200}}]
        html = self.render().stats
        self.assertIn("— XP", html)
        self.assertNotIn("200 XP", html)
        self.assertIn("class=aq-row-day>Streak unknown", html)
        self.assertNotIn("streak at risk today", html)

    def test_a_freeze_is_named_and_expired_days_are_unknown(self):
        self.pending_day()
        self.addon.state["profile"].update(streak_state="protected", at_risk=False)
        self.addon.state["profile"]["today"].update(reviews=0, time_ms=0, minutes=0)
        self.assertIn("Protected by a freeze", self.render().stats)
        self.addon.state["profile"]["day_ends_at"] = int(time.time() * 1000) - 1
        html = self.render().stats
        self.assertNotIn("7 day streak", html)
        self.assertNotIn("Protected by a freeze", html)
        self.assertIn("Streak unknown", html)

    def test_a_review_on_a_protected_day_is_short(self):
        # The freeze kept yesterday; today's review is short of the minimum, not unstudied.
        self.pending_day()
        self.addon.state["profile"].update(streak_state="protected", at_risk=False)
        view = self.home._profile_for_display(self.addon.state["profile"])
        self.assertEqual("short", self.home.moods.day_state(view))
        self.assertNotIn("Protected by a freeze", self.render().stats)
        self.assertIn("Not yet", self.home._toolbar_values()[0])
        finished = self.addon.state["profile"]["today"]["starts_at"] + 1
        self.assertEqual("short", self.home._session_day({"finished_at": finished})["state"])

    def test_the_flame_follows_todays_mood(self):
        # Short of the minimum: grey; counted: lit; a freeze: icy blue; an ended day: none.
        self.pending_day()
        html = self.render().stats
        self.assertIn("7 day streak", html)
        self.assertNotIn("\U0001f525 7 day streak", html)
        self.assertIn("fill='#767676'", html)
        self.addon.state["profile"].update(streak_state="studied")
        self.assertIn("\U0001f525 7 day streak", self.render().stats)
        # A freeze with no study yet; any review would make Aki hopeful and the flame grey.
        self.addon.state["profile"].update(streak_state="protected", at_risk=False)
        self.addon.state["profile"]["today"].update(reviews=0, time_ms=0, minutes=0)
        self.assertIn("fill='#2F86D6'", self.render().stats)
        self.addon.state["profile"]["day_ends_at"] = int(time.time() * 1000) - 1
        html = self.render().stats
        self.assertNotIn("<svg", html)
        self.assertNotIn("\U0001f525 7 day streak", html)

    def test_without_the_collection_the_servers_goal_lights_the_flame(self):
        # The deck list line falls back to the server's goal when the collection cannot be read.
        self.pending_day()
        flames = self.home.moods.Flame
        view = self.home._profile_for_display(self.addon.state["profile"])
        self.assertEqual(flames.UNLIT, self.home.streak_flame(view))
        self.addon.state["profile"]["goal"] = {"reached": True}
        self.assertEqual(flames.LIT, self.home.streak_flame(view))

    def test_the_session_day_waits_for_upload_and_expires_with_the_profile(self):
        self.pending_day()
        finished = int(time.time() * 1000) - 1
        self.review(finished, 60)
        summary = {"finished_at": finished}
        self.assertEqual("syncing", self.home._session_day(summary)["state"])
        self.assertEqual("Streak minimum reached — syncing", self.home._streak_title(summary))
        self.addon.state["profile"].update(streak_state="studied")
        self.assertEqual("met", self.home._session_day(summary)["state"])
        self.assertEqual("Streak secured! 🔥", self.home._streak_title(summary))
        with fixture.patch.object(self.home, "now_ms", return_value=self.addon.state["profile"]["day_ends_at"]):
            self.assertEqual("unknown", self.home._session_day(summary)["state"])

    def test_an_unverified_day_counts_with_time_not_known(self):
        # Observed answers (AnkiQuest Lite) keep today counting short of the minimum.
        self.pending_day()
        self.addon.state["profile"].update(streak_state="unverified", at_risk=False, streak_warning=None)
        self.addon.state["profile"]["today"].update(observed=1)
        html = self.render().stats
        self.assertIn("\U0001f525 7 day streak", html)
        self.assertIn("Studied today · time not known", html)
        self.assertIn("Streak secured: today counts for your streak.", html)
        self.assertNotIn("you reached today", html)
        self.assertNotIn("Syncing", html)
        self.assertIn("Secured", self.home._toolbar_values()[0])
        summary = {"finished_at": self.addon.state["profile"]["today"]["starts_at"] + 1}
        self.assertEqual({"state": "unverified", "label": "Studied today · time not known"}, self.home._session_day(summary))
        self.assertEqual("Streak secured! 🔥", self.home._streak_title(summary))

    def test_past_session_days_keep_the_servers_distinct_verdicts(self):
        self.pending_day()
        profile = self.addon.state["profile"]
        for state, label in (
            ("met", "Streak minimum met"), ("short", "Short of the streak minimum"),
            ("frozen", "Frozen — streak kept"), ("skipped", "Skipped day — streak kept"),
            ("none", "No study counted"), ("unverified", "Time not known"),
        ):
            with self.subTest(state=state):
                profile["heatmap"] = [{"date": "2024-01-01", "state": state}]
                self.assertEqual({"state": state, "label": label}, self.home._session_day({"day": "2024-01-01", "finished_at": 1}))
        self.assertEqual("unknown", self.home._session_day({"day": "2023-12-01", "finished_at": 1})["state"])


if __name__ == "__main__":
    unittest.main()
