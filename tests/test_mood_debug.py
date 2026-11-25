"""The hidden debug menu's override of today's mood and pose: states, transitions, thresholds
and that nothing of it leaves the device (mood_debug, moods with thresholds)."""

import unittest

from addon_loader import load_in_package

debug = load_in_package("aq_mood_debug", "mood_debug")
moods = load_in_package("aq_moods", "moods")


class Override(unittest.TestCase):
    def test_without_a_choice_it_follows_today(self):
        kind, value = debug.Override.read({})
        self.assertIs(kind, debug.Override.AUTO)
        self.assertIsNone(value)
        self.assertEqual("fire", debug.mood("fire", kind, value))
        self.assertIsNone(debug.marker(kind))

    def test_a_mood_choice_replaces_the_computed_mood_until_cleared(self):
        kind, value = debug.Override.read({"debug_override": "mood:frozen_2"})
        self.assertIs(kind, debug.Override.MOOD)
        self.assertEqual("frozen_2", debug.mood("fire", kind, value))
        self.assertEqual("Debug override", debug.marker(kind))
        # Clearing goes back to following today.
        kind, value = debug.Override.read({"debug_override": debug.stored(kind, "")})
        self.assertIs(kind, debug.Override.AUTO)
        self.assertEqual("fire", debug.mood("fire", kind, value))
        self.assertIsNone(debug.marker(kind))

    def test_a_pose_choice_replaces_the_pose_and_keeps_the_mood(self):
        kind, value = debug.Override.read({"debug_override": "pose:sad"})
        self.assertIs(kind, debug.Override.POSE)
        self.assertEqual("fire", debug.mood("fire", kind, value))
        self.assertEqual("aki_sad", debug.pose("aki", "fire", 5, kind, value))
        self.assertEqual("ankilope_sad", debug.pose("ankilope", "fire", 5, kind, value))
        self.assertEqual("Debug override", debug.marker(kind))

    def test_a_mood_choice_picks_its_own_pose(self):
        kind, value = debug.Override.read({"debug_override": "mood:asleep"})
        self.assertEqual(moods.AKI_POSES[moods._MOOD_POSE_NAMES["asleep"]], debug.pose("aki", "fire", 5, kind, value))

    def test_unknown_kinds_and_values_fall_back_to_following_today(self):
        for stored in ("mood:nope", "pose:aki_sad", "snow:fire", "mood", "1"):
            with self.subTest(stored=stored):
                kind, value = debug.Override.read({"debug_override": stored})
                self.assertIs(kind, debug.Override.AUTO)
                self.assertIsNone(value)
                self.assertIsNone(debug.marker(kind))

    def test_the_states_round_trip_through_the_config_entry(self):
        for kind, value in ((debug.Override.AUTO, None), (debug.Override.MOOD, "sad"), (debug.Override.POSE, "frozen")):
            stored = debug.stored(kind, value)
            read = debug.Override.read({"debug_override": stored})
            self.assertEqual((kind, value), read, stored)

    def test_the_flame_follows_the_shown_mood(self):
        kind, value = debug.Override.read({"debug_override": "mood:frozen_2"})
        self.assertEqual("icy", debug.flame("fire", kind, value).value)


class Thresholds(unittest.TestCase):
    def test_the_limits_must_stay_ordered(self):
        self.assertTrue(debug.ordered(debug.thresholds({})))
        for broken in (
            {"hot_days": 5, "blazing_days": 5},
            {"blazing_days": 40, "legend_days": 40},
            {"frozen_2_days": 4, "frozen_3_days": 4},
            {"hot_days": 30, "blazing_days": 7},
        ):
            with self.subTest(broken=broken):
                limits = debug.thresholds({})
                limits.update(broken)
                self.assertFalse(debug.ordered(limits), broken)

    def test_without_edits_every_limit_keeps_its_rule_value(self):
        self.assertEqual(debug.DEFAULT_THRESHOLDS, debug.thresholds({}))
        self.assertEqual({"hot_days": 7, "blazing_days": 30, "legend_days": 100}, {
            name: debug.thresholds({})[name] for name in ("hot_days", "blazing_days", "legend_days")
        })

    def test_edited_limits_change_where_the_hotter_poses_start(self):
        limits = debug.thresholds({"debug_thresholds": {"hot_days": 2, "blazing_days": 3, "legend_days": 4}})
        self.assertEqual("aki_streak_hot", moods.streak_pose(moods.FIRE, 2, limits))
        self.assertEqual("aki_streak_blazing", moods.streak_pose(moods.FIRE, 3, limits))
        self.assertEqual("aki_streak_legend", moods.streak_pose(moods.FIRE, 4, limits))

    def test_edited_limits_change_where_the_frozen_moods_start(self):
        limits = debug.thresholds({"debug_thresholds": {"frozen_2_days": 3, "frozen_3_days": 5}})
        self.assertEqual(moods.FROZEN_1, moods._frozen(2, limits))
        self.assertEqual(moods.FROZEN_2, moods._frozen(3, limits))
        self.assertEqual(moods.FROZEN_3, moods._frozen(5, limits))

    def test_only_whole_numbers_one_and_up_move_a_limit(self):
        for wrong in ("7", 0, -1, 2.5, True, None):
            with self.subTest(wrong=wrong):
                limits = debug.thresholds({"debug_thresholds": {"hot_days": wrong}})
                self.assertEqual(7, limits["hot_days"])

    def test_rule_values_stay_untouched_without_an_edit(self):
        # The pinned streak-mood fixtures keep passing with the thresholds at their defaults.
        self.assertEqual(moods.FROZEN_2, moods._frozen(2))
        self.assertEqual(moods.FROZEN_3, moods._frozen(3))
        self.assertEqual("aki_streak_hot", moods.streak_pose(moods.FIRE, 7))
        self.assertEqual("aki_streak", moods.streak_pose(moods.FIRE, 2))

    def test_storing_drops_limits_left_at_their_rule(self):
        self.assertEqual({}, debug.thresholds_stored({"hot_days": 7, "blazing_days": 30}))
        self.assertEqual({"hot_days": 4}, debug.thresholds_stored({"hot_days": 4}))


class NeverSentToTheServer(unittest.TestCase):
    def test_the_know_synced_settings_leave_the_debug_keys_alone(self):
        # The debug keys are not among the settings the add-on syncs.
        synced = load_in_package("aq_settings_sync", "settings_sync")
        self.assertNotIn("debug_override", getattr(synced, "SYNCED", ()) or ())
        self.assertNotIn("debug_thresholds", getattr(synced, "SYNCED", ()) or ())
        keys = set(getattr(synced, "SYNCED", ()) or ()) or set(vars(synced))
        for name in ("debug_override", "debug_thresholds"):
            self.assertNotIn(name, keys)
