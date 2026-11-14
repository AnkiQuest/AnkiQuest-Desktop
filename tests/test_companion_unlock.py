"""The hidden cow: the shared tap rule, unlocks kept until the server has them, and its art."""

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

FIXTURE = json.loads((ADDON.parent / "tests/fixtures/companion_unlock.json").read_text("utf-8"))
EXAMPLES = ADDON.parent / "docs/api/examples"


class TapRule(unittest.TestCase):
    def test_the_rule_is_the_shared_one(self):
        self.assertEqual(FIXTURE["taps"], unlock.TAPS)
        self.assertEqual(FIXTURE["max_gap_ms"], unlock.MAX_GAP_MS)

    def test_every_shared_case(self):
        self.assertTrue(FIXTURE["cases"])
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["name"]):
                taps = unlock.Taps()
                found = [taps.tap(choice, at_ms) for choice, at_ms in case["sequence"]]
                self.assertEqual(case["unlocks"], found[-1])
                self.assertFalse(any(found[:-1]), "only the last tap may unlock")

    def test_the_count_starts_again_after_an_unlock(self):
        taps = unlock.Taps()
        found = [taps.tap("ankilope", index * 100) for index in range(2 * unlock.TAPS)]
        self.assertEqual([unlock.TAPS - 1, 2 * unlock.TAPS - 1], [index for index, done in enumerate(found) if done])


class KeptUnlocks(unittest.TestCase):
    def setUp(self):
        self.prefs = {}
        self.api = SimpleNamespace(base="https://example.test", name="hill")
        self.key = unlock.account(self.api)

    def test_an_unlock_waits_until_the_server_lists_it(self):
        unlock.record(self.prefs, self.key, "cow")
        self.assertEqual(["cow"], unlock.pending(self.prefs, self.key))
        self.assertEqual({"cow"}, unlock.unlocked(self.prefs, self.key))
        unlock.settle(self.prefs, self.key, ["cow"])
        self.assertEqual([], unlock.pending(self.prefs, self.key))
        self.assertEqual({"cow"}, unlock.unlocked(self.prefs, self.key))

        # Recording it again once sent does not send it again.
        unlock.record(self.prefs, self.key, "cow")
        self.assertEqual([], unlock.pending(self.prefs, self.key))

    def test_unlocks_belong_to_one_account(self):
        unlock.record(self.prefs, self.key, "cow")
        other = unlock.account(SimpleNamespace(base="https://example.test", name="cerro"))
        self.assertEqual(set(), unlock.unlocked(self.prefs, other))

    def test_an_unlock_from_another_device_counts(self):
        unlock.settle(self.prefs, self.key, ["cow"])
        self.assertEqual({"cow"}, unlock.unlocked(self.prefs, self.key))

    def test_sending_needs_the_servers_capability(self):
        answer = json.loads((EXAMPLES / "unlocks_save.json").read_text("utf-8"))
        api = SimpleNamespace(capabilities=Mock(return_value=frozenset([unlock.FEATURE])), unlock=Mock(return_value=answer))
        self.assertEqual(["cow"], unlock.send(api, ["cow"]))
        api.unlock.assert_called_once_with("cow")

        older = SimpleNamespace(capabilities=Mock(return_value=frozenset()), unlock=Mock())
        self.assertIsNone(unlock.send(older, ["cow"]))
        older.unlock.assert_not_called()

    def test_the_servers_list_is_read_from_the_example(self):
        answer = json.loads((EXAMPLES / "unlocks.json").read_text("utf-8"))
        api = SimpleNamespace(unlocks=Mock(return_value=answer))
        self.assertEqual(["cow"], unlock.fetch(api, frozenset([unlock.FEATURE])))
        self.assertIsNone(unlock.fetch(api, frozenset()))
        api.unlocks.return_value = {"unlocks": ["cow", 3, None]}
        self.assertEqual(["cow"], unlock.fetch(api, frozenset([unlock.FEATURE])))


class Client(unittest.TestCase):
    def test_unlock_requests(self):
        api = client.Client("https://example.test", "hill", "secret")
        api._request = Mock(return_value={"unlocks": ["cow"]})
        api.unlocks()
        api._request.assert_called_with("/api/unlocks/hill")
        api.unlock("cow")
        api._request.assert_called_with("/api/unlocks/hill", {"unlock": "cow"})

    def test_the_cow_can_be_saved_and_read(self):
        self.assertIn("cow", client.COMPANIONS)
        api = client.Client("https://example.test", "hill", "secret")
        api._request = Mock(return_value={"companion": "cow"})
        self.assertEqual("cow", api.companion())


class CowArt(unittest.TestCase):
    def test_the_cow_is_drawn_with_ankilope_turned_purple(self):
        self.assertEqual("ankilope", moods.art_owner("cow"))
        self.assertEqual("aki", moods.art_owner("aki"))
        self.assertEqual("ankilope_study", moods.companion_pose("cow", "aki_at_risk"))
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
