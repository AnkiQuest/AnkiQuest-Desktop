"""Aki's streak mood agrees with the cases both clients share."""

import json
import re
import unittest
from pathlib import Path

from addon_loader import ADDON, load_module

moods = load_module("aq_streak_moods", "moods.py")

TESTS = Path(__file__).resolve().parent
FIXTURE = TESTS / "fixtures" / "streak_moods.json"

# Art's poses.json, copied beside the code from the pinned release.
ART_POSES = ADDON / "poses.json"

# moods.FETCH says how a checkout fetches the add-on's pictures from the pinned release.

# Aki's picture for each mood but fire, which burns by heat: her art for each pose. thawing shows
# frozen and almost shows hopeful; she has no frozen_2 or frozen_3 art, so those show her frozen.
AKI_MOOD_POSES = {
    moods.MOOD_UNKNOWN: "aki_face",
    moods.ASLEEP: "aki_asleep",
    moods.SAD: "aki_sad",
    moods.FREEZE: "aki_freeze",
    moods.NEGLECTED: "aki_neglected",
    moods.ABANDONED: "aki_neglected",
    moods.DEAD: "aki_neglected",
    moods.FROZEN_1: "aki_frozen",
    moods.FROZEN_2: "aki_frozen",
    moods.FROZEN_3: "aki_frozen",
    moods.THAWING: "aki_frozen",
    moods.HOPEFUL: "aki_hopeful",
    moods.ALMOST: "aki_hopeful",
}


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
                stage = moods.Stage.of(today["time_ms"], today["streak_minutes"])
                history = moods.History(today["frozen_days"], today["days_away"], today["freezes"], today["day_left_ms"])
                found = moods.streak_mood(today["state"], today["reviews"], stage, today["streak"], history, goal)
                self.assertEqual(case["expected"]["mood"], found)
                pose = moods.pose_art(moods.AKI_POSES, case["expected"]["pose"])
                self.assertEqual(pose, moods.streak_pose(found, today["streak"]))
                self.assertEqual(pose, moods.mood_pose(moods.AKI, found, today["streak"]))

    def test_every_shared_message_case(self):
        # The Today line for each mood, as Android's Home card (AnkiquestAki.message) picks it.
        cases = self.fixture["messages"]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["name"]):
                profile = {"today": {"reviews": case["reviews"]}}
                found = moods.mood(case["mood"], case["decks_due"], case["focus_due"], profile, 0)
                self.assertEqual(case["expected"], found)

    def test_a_waiting_streak_names_its_days(self):
        self.assertEqual(("You haven’t studied today. Your %d-day streak is still waiting.", (64,)),
                         moods.message(moods.AKI, moods.WAITING, 64))
        self.assertEqual(("You haven’t studied today. Your 1-day streak is still waiting.", ()),
                         moods.message(moods.ANKILOPE_ID, moods.WAITING, 1))

    def test_every_shared_stage(self):
        # The stage starts are the shared ones, in order, and each boundary case lands in its stage.
        stages = self.fixture["stages"]
        starts = [(start["stage"], start["from_percent"]) for start in stages["starts"]]
        self.assertEqual([(stage.value, stage.percent) for stage in moods.Stage], starts)
        for case in stages["cases"]:
            with self.subTest(case=case):
                self.assertEqual(case["expected"], moods.Stage.of(case["time_ms"], case["streak_minutes"]).value)

    def test_a_review_after_a_freeze_keeps_aki_frozen(self):
        # Regression: one review after a freeze made Aki hopeful at once.
        stage = moods.Stage.of(30_000, 20)
        history = moods.History(frozen_days=1)
        self.assertEqual(moods.FROZEN_1, moods.streak_mood(moods.PROTECTED, 1, stage, 10, history, moods.Goal.OPEN))

    def test_the_displayed_day_sets_the_stage(self):
        # The Today panel and the companion tab measure the day the way its verdict does.
        def view(time_ms):
            return {"_day_status": "protected", "streak": 10, "heatmap": [],
                    "today": {"reviews": 4, "time_ms": time_ms, "streak_minutes": 20}}

        self.assertEqual(moods.FREEZE, moods.today_mood(view(299_999), moods.Goal.OPEN))
        self.assertEqual(moods.THAWING, moods.today_mood(view(300_000), moods.Goal.OPEN))
        self.assertEqual(moods.HOPEFUL, moods.today_mood(view(600_000), moods.Goal.OPEN))
        self.assertEqual(moods.ALMOST, moods.today_mood(view(900_000), moods.Goal.OPEN))

        # Older servers send whole minutes only.
        older = view(0)
        older["today"] = {"reviews": 4, "minutes": 10, "streak_minutes": 20}
        self.assertEqual(moods.HOPEFUL, moods.today_mood(older, moods.Goal.OPEN))

    def test_every_shared_frozen_run(self):
        for case in self.fixture["frozen_run"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(case["expected"], moods.frozen_run(case["heatmap"]))

    def test_every_shared_away_run(self):
        for case in self.fixture["away_run"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(case["expected"], moods.away_run(case["heatmap"]))

    def test_every_shared_freeze_picture_case(self):
        end = 86_400_000
        for case in self.fixture["freeze_used"]["cases"]:
            with self.subTest(case=case["name"]):
                seen = end if case["opened_today"] else 0
                picture = moods.freeze_picture(moods.AKI, case["frozen_days"], end, seen)
                self.assertEqual("aki_freeze_used" if case["expected"] else None, picture)

    def test_only_a_current_enabled_freeze_changes_the_mood(self):
        now = 86_400_000
        end = now + self.fixture["freeze_window_ms"]
        view = {"_day_status": "pending", "streak": 7, "day_ends_at": end,
                "stored_freezes": 1, "freezes_enabled": True}
        self.assertEqual(moods.SAD, moods.today_mood(view, moods.Goal.OPEN, now_ms=now - 1))
        self.assertEqual(moods.FREEZE, moods.today_mood(view, moods.Goal.OPEN, now_ms=now))
        self.assertEqual(moods.SAD, moods.today_mood(view, moods.Goal.OPEN, now_ms=end))
        self.assertEqual(moods.SAD, moods.today_mood(dict(view, freezes_enabled=False), moods.Goal.OPEN, now_ms=now))

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
        # Each pose and Today art is bundled and the web view may load it, but nothing outside the art.
        source = (ADDON / "__init__.py").read_text("utf-8")
        pattern = re.search(r'setWebExports\(__name__, r"(.+?)"\)', source).group(1)
        self.assertTrue(re.fullmatch(pattern, "art/bluma_face.png"))
        self.assertFalse(re.fullmatch(pattern, "aki_face.png"), "faces load from art/")
        self.assertFalse(re.fullmatch(pattern, "art/../config.json"))
        for companion in ("aki", "ankilope", "cow", "anki_tan"):
            shown = {moods.mood_pose(companion, chosen, streak) for chosen in moods.STREAK_MOODS for streak in (0, 1, 7, 30, 100)}
            shown.add(moods.companion_pose(companion, "aki_streak_milestone"))
            shown.update(moods.art(companion, mood) for mood in moods.MOODS)
            shown.discard(None)
            for pose in shown:
                name = "art/%s.png" % pose
                self.assertTrue((ADDON / name).is_file(), name)
                self.assertTrue(re.fullmatch(pattern, name), name)
        self.assertIsNone(moods.companion_pose("none", "aki_at_risk"))

    def test_every_picture_asked_for_is_exported_or_falls_back(self):
        # The pictures come from the pinned AnkiQuest-Art release (docs/desktop.md, Companion pictures).
        # Every pose Art's poses.json names resolves, for every companion, to an exported picture or
        # to the exported picture of its fallback, and so does every picture named directly.
        self.assertTrue((ADDON / "art").is_dir(), "Fetch the pictures first: " + moods.FETCH)
        poses = [*moods.CORE_POSES, *moods.POSE_FALLBACKS]

        asked = set()
        for art in (moods.AKI_POSES, moods.ANKILOPE, moods.BLUMA_POSES, moods.ANKI_TAN_POSES):
            asked.update(art.values())
        scenes = ["aki_" + scene for scene in moods.PICTURE_FALLBACKS]
        for companion in ("aki", "ankilope", "cow", "anki_tan"):
            owner = moods.companion_poses(companion)
            asked.update(moods.pose_art(owner, pose) for pose in poses)
            asked.update(moods.companion_pose(companion, aki) for aki in moods._AKI_PICTURES)
            if companion != "aki":
                asked.update(moods.companion_pose(companion, aki) for aki in scenes)
            asked.update(moods.preview(companion))
        for name in sorted(asked):
            with self.subTest(picture=name):
                self.assertTrue((ADDON / "art" / (name + ".png")).is_file(), name)

    def test_asleep_art_uses_the_pose_name(self):
        # AnkiQuest-Server#32: every companion's asleep picture is `<companion>_asleep`.
        for poses in (moods.AKI_POSES, moods.ANKILOPE, moods.BLUMA_POSES, moods.ANKI_TAN_POSES):
            name = poses["asleep"]
            self.assertTrue(name.endswith("_asleep"), name)
            self.assertTrue((ADDON / "art" / ("%s.png" % name)).is_file(), name)

    def test_ankilope_shows_her_pose_for_every_mood(self):
        # Regression: a freeze used yesterday showed Ankilope studying, although her frozen art exists.
        # On fire she shows her streak pose, at every heat.
        expected = {
            moods.MOOD_UNKNOWN: "ankilope_face",
            moods.ASLEEP: "ankilope_asleep",
            moods.SAD: "ankilope_sad",
            moods.FREEZE: "ankilope_frozen",
            moods.NEGLECTED: "ankilope_neglected",
            moods.ABANDONED: "ankilope_neglected",
            moods.DEAD: "ankilope_neglected",
            moods.FROZEN_1: "ankilope_frozen",
            moods.FROZEN_2: "ankilope_frozen",
            moods.FROZEN_3: "ankilope_frozen",
            moods.THAWING: "ankilope_frozen",
            moods.HOPEFUL: "ankilope_hopeful",
            moods.ALMOST: "ankilope_hopeful",
            moods.FIRE: "ankilope_streak",
        }
        self.assertEqual(set(moods.STREAK_MOODS), set(expected))
        for chosen, pose in expected.items():
            for streak in (0, 1, 7, 30, 100, 365):
                with self.subTest(mood=chosen, streak=streak):
                    self.assertEqual(pose, moods.mood_pose(moods.ANKILOPE_ID, chosen, streak))

    def test_anki_tan_shows_her_pose_for_every_mood(self):
        # Anki-tan goes live with the poses her masters have; frozen 2 and 3 fall
        # back to frozen until they are drawn (AnkiQuest-Server#57).
        expected = {
            moods.MOOD_UNKNOWN: "anki_tan_face",
            moods.ASLEEP: "anki_tan_asleep",
            moods.SAD: "anki_tan_sad",
            moods.FREEZE: "anki_tan_frozen",
            moods.NEGLECTED: "anki_tan_neglected",
            moods.ABANDONED: "anki_tan_neglected",
            moods.DEAD: "anki_tan_neglected",
            moods.FROZEN_1: "anki_tan_frozen",
            moods.FROZEN_2: "anki_tan_frozen",
            moods.FROZEN_3: "anki_tan_frozen",
            moods.THAWING: "anki_tan_frozen",
            moods.HOPEFUL: "anki_tan_hopeful",
            moods.ALMOST: "anki_tan_hopeful",
        }
        self.assertEqual(set(moods.STREAK_MOODS) - {moods.FIRE}, set(expected))
        for chosen, pose in expected.items():
            for streak in (0, 1, 7, 30, 100, 365):
                with self.subTest(mood=chosen, streak=streak):
                    self.assertEqual(pose, moods.mood_pose(moods.ANKI_TAN, chosen, streak))

        # On fire she shows her streak pose; its hotter tiers are not drawn and fall back to it.
        for streak in (1, 7, 30, 99, 100, 365):
            self.assertEqual("anki_tan_streak", moods.mood_pose(moods.ANKI_TAN, moods.FIRE, streak))

    def test_anki_tan_shows_her_pose_for_aki_pictures(self):
        pose = lambda aki: moods.companion_pose(moods.ANKI_TAN, aki)
        self.assertEqual("anki_tan_frozen", pose("aki_freeze"))
        self.assertEqual("anki_tan_hopeful", pose("aki_nudge"), "no scene art: the pose poses.json names, never her face")
        self.assertEqual(["anki_tan_face", "anki_tan_streak", "anki_tan_sad"], moods.preview(moods.ANKI_TAN))

        # Welcome is her hopeful master; her other extensions fall back as poses.json says.
        fallbacks = {
            "review": "anki_tan_happy", "winner": "anki_tan_happy",
            "leech_defeated": "anki_tan_happy", "streak_hot": "anki_tan_streak",
            "streak_blazing": "anki_tan_streak", "streak_legend": "anki_tan_streak",
            "streak_milestone": "anki_tan_streak",
            "frozen_2": "anki_tan_frozen", "frozen_3": "anki_tan_frozen",
            "hurt": "anki_tan_sad", "abandoned": "anki_tan_neglected", "dead": "anki_tan_neglected",
        }
        for pose_name, art in fallbacks.items():
            self.assertNotIn(pose_name, moods.ANKI_TAN_POSES)
            self.assertEqual(art, moods.pose_art(moods.ANKI_TAN_POSES, pose_name), pose_name)

    def test_a_companion_without_art_is_drawn_as_aki(self):
        self.assertEqual("aki", moods.art_owner("leech_kun"))
        self.assertEqual("aki_sad", moods.mood_pose("leech_kun", moods.SAD, 3))

    def test_aki_shows_her_core_pose_for_every_mood(self):
        # Her sad, hopeful and frozen art shipped, but the moods showed older pictures. Frozen 2 and 3
        # have no art of their own and fall back to frozen.
        for chosen, pose in AKI_MOOD_POSES.items():
            for streak in (0, 1, 7, 30, 100, 365):
                with self.subTest(mood=chosen, streak=streak):
                    self.assertEqual(pose, moods.mood_pose(moods.AKI, chosen, streak))
        self.assertEqual("aki_streak_hot", moods.mood_pose(moods.AKI, moods.FIRE, 7))
        self.assertEqual("aki_frozen", moods.pose_art(moods.AKI_POSES, "frozen_3"))

    def test_ankilope_shows_her_pose_for_aki_pictures(self):
        # Aki's welcome picture stays Ankilope's welcome; only the hopeful mood shows her hopeful.
        self.assertEqual("ankilope_welcome", moods.companion_pose(moods.ANKILOPE_ID, "aki_welcome"))
        self.assertEqual("ankilope_asleep", moods.companion_pose(moods.ANKILOPE_ID, "aki_asleep"))
        self.assertEqual("ankilope_frozen", moods.companion_pose(moods.ANKILOPE_ID, "aki_freeze"))
        self.assertEqual("ankilope_streak", moods.companion_pose(moods.ANKILOPE_ID, "aki_streak_milestone"))
        self.assertEqual("ankilope_study", moods.companion_pose(moods.ANKILOPE_ID, "aki_review"))
        self.assertEqual(["ankilope_face", "ankilope_streak", "ankilope_sad"], moods.preview(moods.ANKILOPE_ID))

    def test_the_poses_come_from_the_pinned_art_release(self):
        # The pose list is Art's: the release's poses.json, unpacked beside the code, not a copy
        # on the server. Its core poses, extension fallbacks and core fallbacks are what moods
        # works with, with nothing of its own on top.
        self.assertTrue(ART_POSES.is_file(), "Fetch the pictures first: " + moods.FETCH)
        art = json.loads(ART_POSES.read_text("utf-8"))
        self.assertEqual(art["core"], list(moods.CORE_POSES))
        self.assertEqual({**art["extensions"], **art["pictures"]}, moods.POSE_FALLBACKS)
        self.assertEqual(art["core_fallbacks"], moods.CORE_FALLBACKS)

        # Every companion has every core pose, so no core fallback is used.
        for art in (moods.AKI_POSES, moods.ANKILOPE, moods.BLUMA_POSES, moods.ANKI_TAN_POSES):
            self.assertTrue(set(moods.CORE_POSES) <= set(art))
        self.assertLessEqual(set(moods.CORE_FALLBACKS.values()), set(moods.CORE_POSES))
        self.assertEqual("ankilope_frozen", moods.pose_art(moods.ANKILOPE, "frozen_3"))

    def test_poses_are_read_from_art(self):
        # The core poses every companion has, the pose each extension falls back to and the core
        # pose shown while one is not drawn, as Art's poses.json names them.
        art = json.dumps({
            "core": ["face", "asleep"],
            "extensions": {"winner": "happy", "frozen_2": "frozen"},
            "pictures": {"freeze": "frozen"},
            "core_fallbacks": {"happy": "hopeful"},
        })
        self.assertEqual(
            (("face", "asleep"), {"winner": "happy", "frozen_2": "frozen", "freeze": "frozen"}, {"happy": "hopeful"}),
            moods.read_poses(art),
        )
        for missing in ("core", "extensions", "pictures", "core_fallbacks"):
            with self.subTest(missing=missing):
                stripped = {key: value for key, value in json.loads(art).items() if key != missing}
                with self.assertRaises(ValueError):
                    moods.read_poses(json.dumps(stripped))
        for name, wrong in (
            ("core poses that are not strings", {"core": ["face", 7]}),
            ("core that is not a list", {"core": "face"}),
            ("fallbacks that are not strings", {"extensions": {"winner": 7}}),
            ("picture fallbacks that are not strings", {"pictures": {"freeze": 7}}),
            ("core fallbacks that are not strings", {"core_fallbacks": {"happy": 7}}),
        ):
            with self.subTest(wrong=name):
                broken = dict(json.loads(art), **wrong)
                with self.assertRaises(ValueError):
                    moods.read_poses(json.dumps(broken))

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
