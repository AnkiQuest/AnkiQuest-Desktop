"""Each companion shows its own exported pose in every slot, as the phone's AnkiquestCompanionArtTest
pins: the picker and toolbar face, each mood's pose and each scene. Fallbacks are the ones
AnkiQuest-Art's poses.json names; only the face is a headshot, and no picture is recoloured."""

import json
import re
import unittest
from pathlib import Path

from addon_loader import ADDON, load_in_package

moods = load_in_package("aq_companion_art", "moods")
share = load_in_package("aq_companion_art", "share")

POSES = ADDON / "poses.json"

# Each companion's id and the prefix of its exported pictures.
PREFIXES = {"aki": "aki_", "ankilope": "ankilope_", "cow": "bluma_", "anki_tan": "anki_tan_"}

# Each companion's picture for every core pose, as the pinned release exports them.
CORE = {
    "aki": {
        "face": "aki_face", "asleep": "aki_asleep", "happy": "aki_celebrate", "streak": "aki_streak",
        "sad": "aki_sad", "hopeful": "aki_hopeful", "frozen": "aki_frozen", "neglected": "aki_neglected",
    },
    "ankilope": {
        "face": "ankilope_face", "asleep": "ankilope_asleep", "happy": "ankilope_celebrate",
        "streak": "ankilope_streak", "sad": "ankilope_sad", "hopeful": "ankilope_hopeful",
        "frozen": "ankilope_frozen", "neglected": "ankilope_neglected",
    },
    "cow": {
        "face": "bluma_face", "asleep": "bluma_asleep", "happy": "bluma_happy", "streak": "bluma_streak",
        "sad": "bluma_sad", "hopeful": "bluma_hopeful", "frozen": "bluma_frozen", "neglected": "bluma_neglected",
    },
    "anki_tan": {
        "face": "anki_tan_face", "asleep": "anki_tan_asleep", "happy": "anki_tan_happy",
        "streak": "anki_tan_streak", "sad": "anki_tan_sad", "hopeful": "anki_tan_hopeful",
        "frozen": "anki_tan_frozen", "neglected": "anki_tan_neglected",
    },
}

# The core pose each streak mood shows; fire shows streak from day one and its tiers fall back to it.
MOOD_POSES = {
    moods.MOOD_UNKNOWN: "face",
    moods.ASLEEP: "asleep",
    moods.SAD: "sad",
    moods.FROZEN_1: "frozen",
    moods.FROZEN_2: "frozen",
    moods.FROZEN_3: "frozen",
    moods.THAWING: "frozen",
    moods.HOPEFUL: "hopeful",
    moods.ALMOST: "hopeful",
    moods.FIRE: "streak",
}

# Aki's scene pictures, which no other companion has, and the core pose each shows through
# poses.json's `pictures` chain (winner and welcome end in happy, review in happy).
SCENES = {
    "aki_nudge": "hopeful",
    "aki_challenge": "hopeful",
    "aki_backlog": "sad",
    "aki_challenge_lost": "sad",
    "aki_place_1": "happy",
    "aki_place_2": "happy",
    "aki_place_3": "happy",
    "aki_challenge_won": "happy",
    "aki_deck_conquered": "happy",
    "aki_level_up": "happy",
    "aki_goal": "happy",
    "aki_achievement": "happy",
}


class CompanionArt(unittest.TestCase):
    def test_the_picker_shows_face_streak_and_sad(self):
        for companion, core in CORE.items():
            with self.subTest(companion=companion):
                self.assertEqual([core["face"], core["streak"], core["sad"]], moods.preview(companion))

    def test_the_toolbar_and_share_face_is_the_companions_own(self):
        for companion, core in CORE.items():
            with self.subTest(companion=companion):
                path = Path(share.face_path(companion))
                self.assertEqual(ADDON / "art" / (core["face"] + ".png"), path)
                self.assertTrue(path.is_file(), "Fetch the pictures first: " + moods.FETCH)
                self.assertEqual(core["face"], moods.face(companion))
        self.assertIsNone(share.face_path("none"))
        self.assertIsNone(moods.face("none"))
        self.assertEqual("aki_face", moods.face("leech_kun"), "no art: Aki's face")

    def test_each_mood_shows_the_companions_own_pose(self):
        for companion, core in CORE.items():
            for chosen, pose in MOOD_POSES.items():
                for streak in (1, 7, 30, 100, 365):
                    if companion == "aki" and chosen == moods.FIRE:
                        continue
                    with self.subTest(companion=companion, mood=chosen, streak=streak):
                        self.assertEqual(core[pose], moods.mood_pose(companion, chosen, streak))

    def test_every_core_pose_is_the_companions_own(self):
        for companion, core in CORE.items():
            for pose, picture in core.items():
                with self.subTest(companion=companion, pose=pose):
                    self.assertEqual(picture, moods.forced_pose(companion, pose))

    def test_extensions_fall_back_as_poses_json_says(self):
        expected = {
            "cow": {"welcome": "bluma_happy", "review": "bluma_happy", "winner": "bluma_happy",
                    "streak_legend": "bluma_streak", "frozen_3": "bluma_frozen", "hurt": "bluma_sad"},
            "anki_tan": {"welcome": "anki_tan_hopeful", "review": "anki_tan_happy", "winner": "anki_tan_happy",
                         "streak_milestone": "anki_tan_streak", "frozen_2": "anki_tan_frozen",
                         "dead": "anki_tan_neglected"},
            "ankilope": {"welcome": "ankilope_welcome", "review": "ankilope_study", "streak_hot": "ankilope_streak"},
        }
        for companion, poses in expected.items():
            table = moods.companion_poses(companion)
            for pose, picture in poses.items():
                with self.subTest(companion=companion, pose=pose):
                    self.assertEqual(picture, moods.pose_art(table, pose))

    def test_scenes_show_the_pose_poses_json_falls_back_to(self):
        for companion, core in CORE.items():
            if companion == "aki":
                continue
            for scene, pose in SCENES.items():
                with self.subTest(companion=companion, scene=scene):
                    self.assertEqual(core[pose], moods.companion_pose(companion, scene))

    def test_the_scene_fallbacks_are_the_shared_ones(self):
        fixture = json.loads(POSES.read_text("utf-8"))
        self.assertEqual(fixture["pictures"], moods.PICTURE_FALLBACKS)

    def test_only_the_face_is_a_headshot(self):
        # Every picture but the face is full body: no face stands in for a pose or a scene.
        everything = [*moods.CORE_POSES, *moods.POSE_FALLBACKS]
        for companion, core in CORE.items():
            table = moods.companion_poses(companion)
            shown = {pose: moods.pose_art(table, pose) for pose in everything if pose != "face"}
            shown.update({scene: moods.companion_pose(companion, scene) for scene in SCENES})
            for slot, picture in shown.items():
                with self.subTest(companion=companion, slot=slot):
                    self.assertNotEqual(core["face"], picture)
                    self.assertTrue(picture.startswith(PREFIXES[companion]), picture)

    def test_every_picture_is_exported_and_may_be_loaded(self):
        source = (ADDON / "__init__.py").read_text("utf-8")
        pattern = re.search(r'setWebExports\(__name__, r"(.+?)"\)', source).group(1)
        everything = [*moods.CORE_POSES, *moods.POSE_FALLBACKS]
        for companion in CORE:
            table = moods.companion_poses(companion)
            shown = {moods.pose_art(table, pose) for pose in everything}
            shown.update(moods.companion_pose(companion, scene) for scene in SCENES if companion != "aki")
            for picture in sorted(shown):
                name = "art/%s.png" % picture
                with self.subTest(picture=name):
                    self.assertTrue((ADDON / name).is_file(), "Fetch the pictures first: " + moods.FETCH)
                    self.assertTrue(re.fullmatch(pattern, name), name)

    def test_no_picture_is_recoloured(self):
        # Bluma has her own pictures: nothing in the add-on turns another companion's.
        for path in sorted(ADDON.glob("*.py")):
            text = path.read_text("utf-8")
            self.assertFalse("hue-rotate" in text or "hue_degrees" in text, path.name)


if __name__ == "__main__":
    unittest.main()
