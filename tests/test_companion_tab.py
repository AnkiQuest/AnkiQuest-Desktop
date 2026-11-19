"""The companion tab's mood line and the unlock reveal's states, without Qt."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from addon_loader import ADDON, load_in_package

moods = load_in_package("aq_tab", "moods")
moments = load_in_package("aq_tab", "moments")
board = load_in_package("aq_tab", "board")
reveal = load_in_package("aq_tab", "companion_reveal")

UNLOCKS = json.loads((ADDON.parent / "tests/fixtures/companion_unlock.json").read_text("utf-8"))
EXAMPLES = ADDON.parent / "tests/api-examples"
Phase, Motion, Beam = reveal.Phase, reveal.Motion, reveal.Beam


def unlock_row(**changes):
    rows = json.loads((EXAMPLES / "notifications_companion.json").read_text("utf-8"))
    return {**next(row for row in rows if row.get("moment") == "companion:cow"), **changes}


class MoodLine(unittest.TestCase):
    def test_every_mood_has_a_line(self):
        for mood in moods.STREAK_MOODS:
            with self.subTest(mood=mood):
                text, values = moods.mood_line(mood, 64)
                self.assertTrue(text)
                self.assertEqual(text.count("%d"), len(values))

    def test_the_line_names_the_streak_where_it_matters(self):
        self.assertEqual(("Sad: your %d-day streak is waiting for today’s study.", (64,)), moods.mood_line(moods.SAD, 64))
        self.assertEqual(("On fire: today counts for your %d-day streak.", (12,)), moods.mood_line(moods.FIRE, 12))

        # A reached goal can burn before the server counts the day.
        self.assertEqual((1,), moods.mood_line(moods.FIRE, 0)[1])
        self.assertEqual(((), ()), (moods.mood_line(moods.ASLEEP, 0)[1], moods.mood_line(moods.FROZEN_2, 9)[1]))

    def test_the_tab_and_the_today_panel_share_one_rule(self):
        view = {"_day_status": "pending", "streak": 64, "today": {"reviews": 0}, "heatmap": []}
        self.assertEqual(moods.SAD, moods.today_mood(view, moods.Goal.OPEN))
        self.assertEqual(moods.FIRE, moods.today_mood(view, moods.Goal.REACHED))
        self.assertEqual(moods.MOOD_UNKNOWN, moods.today_mood(None, moods.Goal.OPEN))
        self.assertEqual(moods.streak_pose(moods.SAD, 64), moods.today_pose("aki", view, moods.Goal.OPEN))


class TodayPanel(unittest.TestCase):
    def test_the_companion_opens_the_companion_tab(self):
        today = {"art": "/a.png", "mood": None, "winner": "/w.png"}
        command = "pycmd('%s')" % board.COMPANION_COMMAND
        self.assertEqual("ankiquest:companion", board.COMPANION_COMMAND)
        self.assertIn(command, board.head(today, None, None, lambda text: text))
        self.assertIn(command, board.html(None, mascot="/m.png"))
        self.assertNotIn(command, board.head({"art": None}, None, None, lambda text: text))

    def test_the_companion_shortcut_is_a_labelled_button(self):
        # A button takes focus and opens on Enter or Space; an image with onclick does neither.
        today = {"art": "/a.png", "mood": None}
        for page in (board.head(today, None, None, lambda text: text), board.html(None, mascot="/m.png")):
            self.assertRegex(page, r'<button type=button [^>]*aria-label="Study companion"[^>]*><img [^>]*alt=""[^>]*></button>')
            self.assertNotRegex(page, r"<img [^>]*onclick")


class RevealStates(unittest.TestCase):
    def test_the_full_reveal_falls_beams_bursts_then_shows(self):
        found = reveal.Reveal(Motion.FULL)
        phases = [found.phase]
        while found.duration_ms() is not None:
            found.advance()
            phases.append(found.phase)
        self.assertEqual([Phase.FALLING, Phase.BEAM, Phase.BURST, Phase.SHOWN], phases)
        found.advance()
        self.assertEqual(Phase.SHOWN, found.phase)
        found.close()
        self.assertEqual(Phase.CLOSED, found.phase)

    def test_reduced_motion_only_fades(self):
        found = reveal.Reveal(Motion.REDUCED)
        self.assertEqual(Phase.FADING, found.phase)
        found.advance()
        self.assertEqual(Phase.SHOWN, found.phase)

    def test_a_tap_skips_to_the_companion(self):
        for steps in range(3):
            with self.subTest(steps=steps):
                found = reveal.Reveal(Motion.FULL)
                for _ in range(steps):
                    found.advance()
                found.skip()
                self.assertEqual(Phase.SHOWN, found.phase)
        closed = reveal.Reveal(Motion.FULL)
        closed.close()
        closed.skip()
        closed.advance()
        self.assertEqual(Phase.CLOSED, closed.phase)

    def test_it_lasts_three_to_five_seconds_and_a_fade_less_than_one(self):
        def length_ms(motion):
            # The reveal as the window plays it: each phase's time, then the next phase.
            shown, total = reveal.Reveal(motion), 0
            while shown.duration_ms() is not None:
                total += shown.duration_ms()
                shown.advance()
            return total

        self.assertTrue(3000 <= length_ms(Motion.FULL) <= 5000)
        self.assertLess(length_ms(Motion.REDUCED), 1000)


class Beams(unittest.TestCase):
    def test_every_companion_has_its_beam(self):
        expected = {
            "aki": Beam.WHITE, "ankilope": Beam.BLUE, "cow": Beam.PURPLE,
            "anki_tan": Beam.GOLD, "leech_tan": Beam.GOLD, "anki_tan_chibi": Beam.RAINBOW,
        }
        listed = {"aki"} | {rule["companion"] for rule in UNLOCKS["companions"]}
        self.assertEqual(listed, set(expected))
        for companion, beam in expected.items():
            self.assertEqual(beam, reveal.beam(companion), companion)
        self.assertEqual(Beam.WHITE, reveal.beam("horse"))


class Due(unittest.TestCase):
    def test_an_unread_unlock_plays_the_reveal(self):
        item = moments._notice(unlock_row())
        self.assertEqual("cow", moments.joined(item))
        self.assertEqual(unlock_row()["id"], item["notice"])
        self.assertTrue(reveal.due(item))

    def test_one_read_on_another_device_shows_the_moment_card(self):
        self.assertFalse(reveal.due(moments._notice(unlock_row(read_at=1793183500))))

    def test_other_moments_and_unknown_companions_do_not(self):
        self.assertFalse(reveal.due(moments._notice(unlock_row(moment="companion:horse"))))
        self.assertIsNone(moments.joined(moments._notice(unlock_row(moment="level:3", topic="level"))))
        self.assertFalse(reveal.due(moments._notice(unlock_row(moment="level:3", topic="level"))))

        # Moments saved before the reveal existed carry no notice and stay cards.
        self.assertFalse(reveal.due({"key": "companion:cow", "topic": "companion", "at": 1, "title": "", "body": ""}))


class RevealWindow(unittest.TestCase):
    def test_the_tab_and_the_reveal_with_real_qt(self):
        for script in ("qt_reveal.py",):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name(script))],
                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(0, result.returncode, script + "\n" + result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
