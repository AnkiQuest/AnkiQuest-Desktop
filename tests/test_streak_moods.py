"""Aki's streak mood agrees with the cases both clients share."""

import json
import re
import unittest
from pathlib import Path

from addon_loader import ADDON, load_module

moods = load_module("aq_streak_moods", "moods.py")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "streak_moods.json"


class StreakMoods(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text("utf-8"))

    def test_every_shared_mood_case(self):
        cases = self.fixture["moods"]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["name"]):
                today = case["today"]
                goal = moods.Goal.REACHED if today["goal_reached"] else moods.Goal.OPEN
                found = moods.streak_mood(today["state"], today["reviews"], today["streak"], today["frozen_days"], goal)
                self.assertEqual(case["expected"]["mood"], found)
                self.assertEqual(case["expected"]["pose"], moods.streak_pose(found, today["streak"]))

    def test_every_shared_frozen_run(self):
        for case in self.fixture["frozen_run"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(case["expected"], moods.frozen_run(case["heatmap"]))

    def test_every_shared_flame(self):
        # The flame beside the streak number is lit only once today counts.
        for case in self.fixture["flames"]:
            with self.subTest(mood=case["mood"]):
                self.assertEqual(case["flame"], moods.flame(case["mood"]).value)

    def test_every_mood_has_a_flame(self):
        covered = [case["mood"] for case in self.fixture["flames"]]
        self.assertEqual(sorted(moods.STREAK_MOODS), sorted(covered))

    def test_the_displayed_day_sets_the_flame(self):
        def view(status, reviews=0, streak=7, heatmap=None):
            return {"_day_status": status, "today": {"reviews": reviews}, "streak": streak, "heatmap": heatmap or []}

        frozen = [{"frozen": True}, {"frozen": False}]
        self.assertEqual(moods.Flame.LIT, moods.today_flame(view("met"), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.LIT, moods.today_flame(view("pending"), moods.Goal.REACHED))
        self.assertEqual(moods.Flame.UNLIT, moods.today_flame(view("pending"), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.UNLIT, moods.today_flame(view("pending", 2), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.ICY, moods.today_flame(view("protected"), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.ICY, moods.today_flame(view("pending", heatmap=frozen), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.NONE, moods.today_flame(view("pending", streak=0), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.NONE, moods.today_flame(view("unknown"), moods.Goal.OPEN))
        self.assertEqual(moods.Flame.NONE, moods.today_flame(None, moods.Goal.OPEN))

    def test_every_mood_is_covered(self):
        covered = {case["expected"]["mood"] for case in self.fixture["moods"]}
        self.assertEqual(set(moods.STREAK_MOODS), covered)

    def test_every_pose_ships_for_every_companion(self):
        # Each pose is bundled and the web view may load it.
        source = (ADDON / "__init__.py").read_text("utf-8")
        pattern = re.search(r'setWebExports\(__name__, r"(.+?)"\)', source).group(1)
        poses = {case["expected"]["pose"] for case in self.fixture["moods"]} | {"aki_streak_milestone"}
        for companion in ("aki", "ankilope", "cow"):
            for pose in poses:
                name = "art/%s.png" % moods.companion_pose(companion, pose)
                self.assertTrue((ADDON / name).is_file(), name)
                self.assertTrue(re.fullmatch(pattern, name), name)
        self.assertIsNone(moods.companion_pose("none", "aki_at_risk"))

    def test_the_displayed_day_sets_the_state(self):
        def view(status, reviews=0):
            return {"_day_status": status, "today": {"reviews": reviews}}

        self.assertEqual("studied", moods.day_state(view("met")))
        self.assertEqual("studied", moods.day_state(view("syncing")))
        self.assertEqual("protected", moods.day_state(view("protected")))
        self.assertEqual("pending", moods.day_state(view("pending")))
        self.assertEqual("short", moods.day_state(view("pending", 2)))
        self.assertEqual("unknown", moods.day_state(view("unknown")))
        self.assertEqual("unknown", moods.day_state(None))


if __name__ == "__main__":
    unittest.main()
