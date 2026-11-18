"""Companions earned at milestones: the shared conditions, what the picker offers, and the art."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from addon_loader import ADDON, load_in_package

unlock = load_in_package("aq_cow", "companion_unlock")
moods = load_in_package("aq_cow", "moods")
board = load_in_package("aq_cow", "board")
share = load_in_package("aq_cow", "share")
client = load_in_package("aq_cow", "client")
moments = load_in_package("aq_cow", "moments")

FIXTURE = json.loads((ADDON.parent / "tests/fixtures/companion_unlock.json").read_text("utf-8"))
EXAMPLES = ADDON.parent / "docs/api/examples"
LIVE = [rule for rule in FIXTURE["companions"] if rule["status"] == "live"]
Choice = unlock.Choice


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text("utf-8"))


class SharedConditions(unittest.TestCase):
    def test_the_live_companions_are_the_ones_the_add_on_earns(self):
        self.assertEqual(list(unlock.EARNED), [rule["companion"] for rule in LIVE])
        for rule in LIVE:
            self.assertFalse(rule["secret"], "a secret one would need hiding")
            self.assertIn(rule["companion"], moods.NAMES)
        for rule in FIXTURE["companions"]:
            if rule["status"] == "planned":
                self.assertNotIn(rule["companion"], moods.NAMES, "planned companions have no art yet")

    def test_every_live_condition_is_worded(self):
        texts = {
            "ankilope": ("Reach level 30", "Level 3 of 30"),
            "cow": ("Study for 10 hours in total", "6 of 10 hours"),
        }
        for rule in LIVE:
            progress = {"kind": rule["kind"], "value": 3 if rule["kind"] == unlock.LEVEL else 6, "goal": rule["goal"]}
            words = (unlock.condition(progress, str), unlock.reached(progress, str))
            self.assertEqual(texts[rule["companion"]], words)
        unknown = {"kind": "streak", "value": 1, "goal": 66}
        self.assertIsNone(unlock.condition(unknown, str))
        self.assertIsNone(unlock.reached(unknown, str))

    def test_the_tap_rule_is_the_shared_one(self):
        self.assertEqual(FIXTURE["taps"], unlock.TAPS)
        self.assertEqual(FIXTURE["max_gap_ms"], unlock.MAX_GAP_MS)
        chibi = next(rule for rule in FIXTURE["companions"] if rule["kind"] == "taps")
        self.assertEqual(FIXTURE["taps"], chibi["goal"])
        self.assertTrue(FIXTURE["cases"])
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["name"]):
                taps = unlock.Taps(chibi["requires"])
                found = [taps.tap(choice, at_ms) for choice, at_ms in case["sequence"]]
                self.assertEqual(case["unlocks"], found[-1])
                self.assertFalse(any(found[:-1]), "only the last tap may unlock")

    def test_each_chibi_is_found_on_its_base(self):
        chibis = {rule["requires"]: rule["companion"] for rule in FIXTURE["companions"] if rule["kind"] == "taps"}
        self.assertEqual(chibis, unlock.CHIBIS)
        self.assertEqual("anki_tan_chibi", unlock.chibi_of("anki_tan", {"anki_tan"}))
        self.assertIsNone(unlock.chibi_of("anki_tan", {"cow"}), "her base is locked")
        self.assertIsNone(unlock.chibi_of("cow", {"cow"}), "the cow has no chibi")

    def test_the_hint_is_the_shared_one(self):
        self.assertEqual(FIXTURE["hint_from"], unlock.HINT_FROM)
        templates = FIXTURE["hint"]
        self.assertEqual(templates["one"].replace("{0}", "1"), unlock.hint(unlock.TAPS - 1, str))
        self.assertEqual(templates["other"].replace("{0}", "5"), unlock.hint(unlock.TAPS - 5, str))
        self.assertEqual(list(range(1, unlock.TAPS + 1)), [case["taps"] for case in FIXTURE["hints"]])
        for case in FIXTURE["hints"]:
            with self.subTest(taps=case["taps"]):
                self.assertEqual(case["hint"], unlock.hint(case["taps"], str))

    def test_the_chibi_taps_are_the_shared_ones(self):
        self.assertTrue(FIXTURE["chibi_taps"])
        for case in FIXTURE["chibi_taps"]:
            with self.subTest(case=case["name"]):
                egg = unlock.Egg(case["unlocked"])
                tapped = [egg.tap(choice, at_ms, str) for choice, at_ms in case["sequence"]]
                self.assertEqual(case["hints"], [tap.hint for tap in tapped])
                found = [tap.chibi is not None for tap in tapped]
                self.assertEqual(case["unlocks"], found[-1])
                self.assertFalse(any(found[:-1]), "only the last tap may unlock")


class Offered(unittest.TestCase):
    def test_the_servers_answer_is_read_from_the_examples(self):
        found = unlock.parse(example("unlocks"))
        self.assertEqual({"cow"}, found.unlocks)
        self.assertEqual({"kind": "level", "value": 2, "goal": 30}, found.progress["ankilope"])
        self.assertEqual(found.unlocks, unlock.parse(example("unlocks_save")).unlocks)

        # What cannot be read is left out.
        odd = unlock.parse({"unlocks": ["cow", 3], "progress": {"ankilope": {"kind": "level"}, "x": 1}})
        self.assertEqual(({"cow"}, {}), (set(odd.unlocks), odd.progress))
        self.assertEqual(frozenset(), unlock.parse(None).unlocks)

    def test_a_server_without_unlocks_answers_nothing_unlocked(self):
        api = SimpleNamespace(unlocks=Mock(return_value=example("unlocks")))
        self.assertEqual({"cow"}, unlock.fetch(api, frozenset([unlock.FEATURE])).unlocks)
        older = unlock.fetch(api, frozenset())
        self.assertEqual((frozenset(), {}), (older.unlocks, older.progress))
        api.unlocks.assert_called_once()

    def test_each_companion_is_offered_by_its_state(self):
        locked = unlock.Found([], {"ankilope": {"kind": "level", "value": 3, "goal": 30}, "cow": {"kind": "study_hours", "value": 6, "goal": 10}})
        earned = unlock.Found(["ankilope", "cow"])
        older = unlock.Found()
        cases = (
            # (companion, found, current, offered)
            ("aki", None, "aki", Choice.FREE),
            ("none", locked, "aki", Choice.FREE),
            ("ankilope", locked, "aki", Choice.LOCKED),
            ("cow", locked, "aki", Choice.LOCKED),
            ("ankilope", earned, "aki", Choice.UNLOCKED),
            ("cow", earned, "aki", Choice.UNLOCKED),
            # The current companion stays a choice, however it was chosen.
            ("ankilope", locked, "ankilope", Choice.UNLOCKED),
            # Before the server answers only the current one shows.
            ("ankilope", None, "aki", Choice.HIDDEN),
            # A server from before milestones: Ankilope as it was, the cow only once unlocked.
            ("ankilope", older, "aki", Choice.FREE),
            ("cow", older, "aki", Choice.HIDDEN),
            ("cow", unlock.Found(["cow"]), "aki", Choice.UNLOCKED),
        )
        for companion, found, current, offered in cases:
            with self.subTest(companion=companion, current=current):
                self.assertEqual(offered, unlock.choice(companion, found, current))


class Client(unittest.TestCase):
    def test_saving_says_the_add_on_shows_locks(self):
        api = client.Client("https://example.test", "hill", "secret")
        api._request = Mock(return_value={"companion": "cow"})
        api.unlocks()
        api._request.assert_called_with("/api/unlocks/hill")
        self.assertEqual("cow", api.set_companion("cow"))
        api._request.assert_called_with("/api/companion/hill", {"companion": "cow"}, extra={"X-AnkiQuest-Companions": "milestones"})

    def test_a_found_chibi_is_reported_without_proof(self):
        api = client.Client("https://example.test", "hill", "secret")
        api._request = Mock(return_value=example("unlocks_save"))
        self.assertEqual(example("unlocks_save"), api.unlock("anki_tan_chibi"))
        api._request.assert_called_with("/api/unlocks/hill", {"unlock": "anki_tan_chibi"})

    def test_the_cow_can_be_saved_and_read(self):
        self.assertIn("cow", client.COMPANIONS)
        api = client.Client("https://example.test", "hill", "secret")
        api._request = Mock(return_value={"companion": "cow"})
        self.assertEqual("cow", api.companion())


class UnlockMoment(unittest.TestCase):
    def test_the_moment_shows_the_companion_that_joined(self):
        row = next(row for row in example("notifications_companion") if row.get("moment") == "companion:cow")
        item = moments._notice(row)
        self.assertEqual(("companion", "Bluma joined you!"), (item["topic"], item["title"]))
        self.assertEqual("Bluma joined me!", item["share"]["title"])
        self.assertEqual("cow", moments.shown_companion(item, "aki"))
        self.assertEqual("ankilope_celebrate", moments._pose(item, moments.shown_companion(item, "none")))
        level = moments._notice({**row, "moment": "level:3", "topic": "level"})
        self.assertEqual("aki", moments.shown_companion(level, "aki"))
        horse = moments._notice({**row, "moment": "companion:horse"})
        self.assertEqual("aki", moments.shown_companion(horse, "aki"))

    def test_the_sharing_settings_name_the_new_kind(self):
        sharing = load_in_package("aq_cow", "sharing")
        kinds = [kind for kind, _ in sharing.KINDS]
        self.assertEqual(sorted(kinds), sorted(example("sharing")["policies"]))


class CowArt(unittest.TestCase):
    def test_the_cow_is_drawn_with_ankilope_turned_purple(self):
        self.assertEqual("ankilope", moods.art_owner("cow"))
        self.assertEqual("aki", moods.art_owner("aki"))
        self.assertEqual("ankilope_sad", moods.companion_pose("cow", "aki_at_risk"))
        self.assertEqual("ankilope_face.png", Path(share.face_path("cow")).name)
        self.assertEqual("hue-rotate(250deg)", moods.css_filter("cow"))
        for companion in ("aki", "ankilope", "none"):
            self.assertIsNone(moods.css_filter(companion))
            self.assertEqual("", board.companion_style(companion))
        self.assertIn("img.aq-companion{filter:hue-rotate(250deg)}", board.companion_style("cow"))

    def test_the_deck_list_marks_every_companion_picture(self):
        today = {"art": "/a.png", "mood": None, "winner": "/w.png"}
        self.assertIn('<img class=aq-companion src="/a.png"', board.head(today, None, None, lambda text: text))
        self.assertIn('class=aq-companion src="/m.png"', board.html(None, mascot="/m.png"))

    def test_picker_cards_preview_face_fire_and_sad(self):
        self.assertEqual(("aki_face", "aki_streak", "aki_at_risk"), moods.PREVIEW_POSES)
        self.assertEqual(["aki_face", "aki_streak", "aki_at_risk"], moods.preview("aki"))
        self.assertEqual(["ankilope_face", "ankilope_study"], moods.preview("ankilope"))
        self.assertEqual(moods.preview("ankilope"), moods.preview("cow"))
        self.assertEqual([], moods.preview("none"))
        for companion in ("aki", "ankilope", "cow"):
            for pose in moods.preview(companion):
                self.assertTrue((ADDON / "art" / (pose + ".png")).is_file(), pose)

    def test_the_cow_has_one_name(self):
        self.assertEqual("Bluma", moods.NAMES["cow"])
        mentions = [path.name for path in ADDON.glob("*.py") if "Bluma" in path.read_text("utf-8")]
        self.assertEqual(["moods.py"], mentions)


class PickerWindow(unittest.TestCase):
    def test_the_picker_with_real_qt(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("qt_companion.py"))],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
