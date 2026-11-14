"""Real Qt checks of the companion tab and the unlock reveal, run by test_companion_tab.py."""

from concurrent.futures import Future
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from aqt.qt import QApplication, QImage, QLabel, QPushButton

from addon_loader import ADDON, load_in_package

app = QApplication.instance() or QApplication([])
reveal_ui = load_in_package("reveal_qt", "reveal_ui")
companion_ui = load_in_package("reveal_qt", "companion_ui")
moments = load_in_package("reveal_qt", "moments")
moods = load_in_package("reveal_qt", "moods")
share_ui = load_in_package("reveal_qt", "share_ui")
reveal_ui.tr = companion_ui.tr = share_ui.tr = lambda text: text
Phase, Motion = reveal_ui.Phase, reveal_ui.Motion

ROWS = json.loads((ADDON.parent / "docs/api/examples/notifications_companion.json").read_text("utf-8"))
COW = moments._notice(next(row for row in ROWS if row.get("moment") == "companion:cow"))


def run_now(work, done):
    future = Future()
    future.set_result(work())
    done(future)


def texts(widget, kind):
    return [found.text() for found in widget.findChildren(kind) if found.text() and found.isVisibleTo(widget)]


class CompanionTab(unittest.TestCase):
    def tab(self, current, today):
        api = SimpleNamespace(capabilities=Mock(return_value=frozenset()), companion=Mock(return_value=current), unlocks=Mock())
        mw = SimpleNamespace(taskman=SimpleNamespace(run_in_background=run_now))
        return companion_ui.Picker(None, mw, api, current, Mock(), today)

    def test_the_chosen_companion_shows_in_todays_mood(self):
        tab = self.tab("aki", (moods.SAD, 64))
        art = tab.today.findChild(QLabel, "ankiquest_companion_today")
        self.assertFalse(art.pixmap().isNull())
        self.assertEqual(companion_ui.TODAY_PX, max(art.pixmap().width(), art.pixmap().height()))
        self.assertEqual(["Aki", "Sad: your 64-day streak is waiting for today’s study."], texts(tab.today, QLabel))

        # The picker follows, as before.
        self.assertEqual("Choose who cheers you on.", tab.dialog.findChildren(QLabel)[len(tab.today.findChildren(QLabel))].text())

    def test_each_companion_shows_its_own_art(self):
        on_fire = self.tab("cow", (moods.FIRE, 12))
        self.assertEqual(["Bluma", "On fire: today counts for your 12-day streak."], texts(on_fire.today, QLabel))

    def test_no_companion_shows_no_mood(self):
        tab = self.tab("none", (moods.SAD, 64))
        self.assertIsNone(tab.today.findChild(QLabel, "ankiquest_companion_today"))
        self.assertEqual(["No companion"], texts(tab.today, QLabel))


class Reveal(unittest.TestCase):
    def setUp(self):
        self.chosen = []

    def window(self, how=Motion.FULL, chosen="aki", item=COW, shared=True):
        def sharing(dialog, run, status):
            if not shared:
                return None
            return share_ui.Sharing(dialog, SimpleNamespace(base="https://quest.test"), item["share"], Mock(), run, status)

        window = reveal_ui.RevealWindow(None, item, how, chosen, self.chosen.append, sharing, run_now)
        self.addCleanup(window.dialog.close)
        window.start()
        return window

    def buttons(self, window):
        return texts(window.details, QPushButton)

    def test_the_reveal_plays_its_phases_then_shows_the_companion(self):
        window = self.window()
        seen = []
        while window.reveal.phase != Phase.SHOWN:
            seen.append(window.reveal.phase)
            self.assertFalse(window.details.isVisible(), window.reveal.phase)
            self.assertFalse(window.stage.grab().isNull())
            window.run_for(100)
        self.assertEqual([Phase.FALLING, Phase.BEAM, Phase.BURST], sorted(set(seen), key=seen.index))
        self.assertTrue(window.details.isVisible())
        self.assertEqual(["Bluma joined you!", COW["body"]], texts(window.details, QLabel)[:2])
        self.assertEqual(["Choose Bluma", "Share", "Later"], self.buttons(window))
        self.assertFalse(window.stage.grab().isNull())

    def test_the_beam_shows_the_companions_colour(self):
        window = self.window()
        window.run_for(reveal_ui.companion_reveal.DURATION_MS[Phase.FALLING] + 1000)
        self.assertEqual(Phase.BEAM, window.reveal.phase)
        image = window.stage.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        top = image.pixelColor(reveal_ui.STAGE_WIDTH // 2, 10)
        self.assertGreater(top.blue(), top.green(), "Bluma's beam is purple")
        self.assertGreater(top.red(), top.green(), "Bluma's beam is purple")

    def test_a_click_skips_to_the_companion(self):
        window = self.window()
        window.stage.mousePressEvent(None)
        self.assertEqual(Phase.SHOWN, window.reveal.phase)
        self.assertTrue(window.details.isVisible())

    def test_reduced_motion_fades_in(self):
        self.assertEqual(Motion.REDUCED, reveal_ui.motion(SimpleNamespace(reduce_motion=lambda: True)))
        self.assertEqual(Motion.FULL, reveal_ui.motion(SimpleNamespace(reduce_motion=lambda: False)))
        self.assertEqual(Motion.FULL, reveal_ui.motion(SimpleNamespace()))
        window = self.window(Motion.REDUCED)
        self.assertEqual(Phase.FADING, window.reveal.phase)
        window.run_for(reveal_ui.companion_reveal.DURATION_MS[Phase.FADING])
        self.assertEqual(Phase.SHOWN, window.reveal.phase)

    def test_choose_saves_the_companion_and_closes(self):
        window = self.window()
        window._skip()
        window.choose.click()
        self.assertEqual(["cow"], self.chosen)
        self.assertEqual(Phase.CLOSED, window.reveal.phase)

    def test_later_closes_without_choosing(self):
        window = self.window()
        window._skip()
        window.later.click()
        self.assertEqual([], self.chosen)
        self.assertEqual(Phase.CLOSED, window.reveal.phase)

    def test_closing_mid_animation_stops_it(self):
        window = self.window()
        window.dialog.reject()
        self.assertEqual(Phase.CLOSED, window.reveal.phase)
        window.run_for(10000)
        self.assertEqual(Phase.CLOSED, window.reveal.phase)

    def test_only_what_applies_is_offered(self):
        window = self.window(chosen="cow", shared=False)
        window._skip()
        self.assertEqual(["Later"], self.buttons(window))

    def test_share_shows_the_moment_cards_choices(self):
        window = self.window()
        window._skip()
        window.share.click()
        self.assertIn("Tell friends", self.buttons(window))


if __name__ == "__main__":
    unittest.main()
