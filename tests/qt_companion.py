"""Real Qt checks of the companion picker, run in a separate process by test_companion_unlock.py."""

from concurrent.futures import Future
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from aqt.qt import QApplication, QImage, QLabel, QPushButton, QSize

from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
companion_ui = load_in_package("companion_qt", "companion_ui")
companion_art = load_in_package("companion_qt", "companion_art")
companion_unlock = load_in_package("companion_qt", "companion_unlock")
companion_reveal = load_in_package("companion_qt", "companion_reveal")
share = load_in_package("companion_qt", "share")
companion_ui.tr = lambda text: text

UNLOCKS = frozenset([companion_unlock.FEATURE])
LOCKED = {"unlocks": [], "progress": {
    "ankilope": {"kind": "level", "value": 3, "goal": 30},
    "cow": {"kind": "study_hours", "value": 6, "goal": 10},
}}


class Picker(unittest.TestCase):
    def setUp(self):
        self.answer = LOCKED
        self.api = SimpleNamespace(
            base="https://example.test", name="hill",
            capabilities=Mock(return_value=UNLOCKS), companion=Mock(return_value="aki"),
            unlocks=Mock(side_effect=lambda: self.answer), set_companion=Mock(),
            unlock=Mock(side_effect=lambda unlock: self.answer),
        )
        self.mw = SimpleNamespace(pm=SimpleNamespace(profile={}), taskman=SimpleNamespace(run_in_background=self.run_task))
        self.saved = []

    def run_task(self, work, done):
        future = Future()
        try:
            future.set_result(work())
        except Exception as error:
            future.set_exception(error)
        done(future)

    def picker(self):
        return companion_ui.Picker(None, self.mw, self.api, "aki", self.saved.append)

    def cards(self, picker):
        """The cards in the order the picker shows them."""
        row = picker._row
        return [row.itemAt(index).widget().property("companion") for index in range(row.count())]

    def card(self, picker, companion):
        return picker._cards[companion]

    def texts(self, card):
        return [label.text() for label in card.findChildren(QLabel) if label.text()]

    def test_locked_companions_show_their_condition_and_cannot_be_chosen(self):
        picker = self.picker()
        self.assertEqual(["aki", "ankilope", "cow", "none"], self.cards(picker))
        self.assertEqual(["Ankilope", "Reach level 30", "Level 3 of 30"], self.texts(self.card(picker, "ankilope")))
        self.assertEqual(["Bluma", "Study for 10 hours in total", "6 of 10 hours"], self.texts(self.card(picker, "cow")))
        for companion in ("ankilope", "cow"):
            self.assertFalse(self.card(picker, companion).isEnabled(), companion)
        self.card(picker, "ankilope").click()
        self.assertEqual("aki", picker.chosen())
        self.card(picker, "none").click()
        self.assertEqual("none", picker.chosen())

    def test_an_unlocked_companion_is_chosen_and_saved(self):
        self.answer = {"unlocks": ["cow"], "progress": {"ankilope": LOCKED["progress"]["ankilope"]}}
        picker = self.picker()
        cow = self.card(picker, "cow")
        self.assertTrue(cow.isEnabled())
        self.assertEqual(["Bluma"], self.texts(cow))
        cow.click()
        picker._save()
        self.api.set_companion.assert_called_once_with("cow")
        self.assertEqual(["cow"], self.saved)

    def test_a_server_before_milestones_offers_ankilope_and_hides_the_cow(self):
        self.api.capabilities.return_value = frozenset()
        picker = self.picker()
        self.assertEqual(["aki", "ankilope", "none"], self.cards(picker))
        self.assertTrue(self.card(picker, "ankilope").isEnabled())
        self.api.unlocks.assert_not_called()

    def test_the_current_companion_shows_before_the_server_answers(self):
        self.api.capabilities.side_effect = OSError("offline")
        self.api.companion.return_value = "cow"
        picker = companion_ui.Picker(None, self.mw, self.api, "cow", self.saved.append)
        self.assertEqual(["aki", "cow", "none"], self.cards(picker))
        self.assertEqual("cow", picker.chosen())

    def test_each_card_previews_its_poses(self):
        self.answer = {"unlocks": ["ankilope"], "progress": {}}
        picker = self.picker()
        for companion, count in (("aki", 3), ("ankilope", 2), ("none", 1)):
            labels = [label for label in self.card(picker, companion).findChildren(QLabel) if label.pixmap() is not None and not label.pixmap().isNull()]
            self.assertEqual(count if companion != "none" else 0, len(labels), companion)

    def test_each_card_fits_its_poses_and_lines(self):
        # A button does not size itself by the layout inside it, so the card says how big it is.
        picker = self.picker()
        for companion, card in picker._cards.items():
            with self.subTest(companion=companion):
                wanted = card.layout().sizeHint()
                self.assertGreaterEqual(card.minimumWidth(), wanted.width())
                self.assertGreaterEqual(card.minimumHeight(), wanted.height())

    def test_cards_replaced_by_the_answer_are_hidden_at_once(self):
        picker = self.picker()
        shown = [card for card in picker.dialog.findChildren(QPushButton, companion_ui.CARD) if card.isVisibleTo(picker.dialog)]
        self.assertEqual(sorted(picker._cards.values(), key=id), sorted(shown, key=id))

    def tap(self, picker, times, clock):
        """Taps the companion's picture `times` times, 300 ms apart on `clock`."""
        art = picker.today.findChild(QLabel, companion_ui.TODAY_ART)
        for _ in range(times):
            clock[0] += 300
            art.tap()
        return art

    def egg(self, unlocks, motion=companion_reveal.Motion.REDUCED):
        """The tab for a player whose companion is Anki-tan, with `unlocks`, on a fake clock."""
        self.answer = {"unlocks": unlocks, "progress": {}}
        self.api.companion.return_value = "anki_tan"
        clock = [0]
        picker = companion_ui.Picker(None, self.mw, self.api, "anki_tan", self.saved.append, motion=motion, clock=lambda: clock[0])
        return picker, clock

    def test_tapping_an_unlocked_base_hints_and_finds_her_chibi(self):
        picker, clock = self.egg(["anki_tan"])
        art = self.tap(picker, 3, clock)
        self.assertTrue(picker._hint.isHidden())
        self.tap(picker, 1, clock)
        self.assertEqual("You are 5 taps away from chibi", picker._hint.text())
        self.assertFalse(picker._hint.isHidden())
        self.tap(picker, 4, clock)
        self.assertEqual("You are 1 tap away from chibi", picker._hint.text())
        self.api.unlock.assert_not_called()
        self.assertEqual("anki_tan", art.property("companion"))

        # The ninth tap turns her chibi and tells the server, without proof.
        self.tap(picker, 1, clock)
        self.assertEqual("anki_tan_chibi", art.property("companion"))
        self.assertTrue(picker._hint.isHidden())
        self.api.unlock.assert_called_once_with("anki_tan_chibi")

    def test_the_chibi_pops_in_unless_motion_is_reduced(self):
        picker, clock = self.egg(["anki_tan"], companion_reveal.Motion.FULL)
        art = self.tap(picker, 9, clock)
        self.assertIsNotNone(picker._pop, "she grows in")
        picker._pop.setCurrentTime(picker._pop.duration())
        self.assertEqual(companion_ui.TODAY_PX, max(art.pixmap().width(), art.pixmap().height()))
        reduced, clock = self.egg(["anki_tan"])
        self.tap(reduced, 9, clock)
        self.assertIsNone(reduced._pop, "no animation with reduced motion")

    def test_tapping_a_locked_base_counts_nothing(self):
        # The server does not list her as unlocked: no hint and no chibi.
        picker, clock = self.egg([])
        art = self.tap(picker, 9, clock)
        self.assertTrue(picker._hint.isHidden())
        self.assertEqual("anki_tan", art.property("companion"))
        self.api.unlock.assert_not_called()

    def test_tapping_a_companion_without_a_chibi_counts_nothing(self):
        picker = self.picker()
        art = self.tap(picker, 9, [0])
        self.assertTrue(picker._hint.isHidden())
        self.assertEqual("aki", art.property("companion"))
        self.api.unlock.assert_not_called()

    def test_a_silhouette_keeps_the_shape_and_drops_the_colours(self):
        face = companion_art.pixmap(share.face_path("ankilope"), "ankilope")
        shadow = companion_art.silhouette(face).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        plain = face.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        colours = set()
        for x in range(0, plain.width(), 4):
            y = plain.height() // 2
            self.assertEqual(plain.pixelColor(x, y).alpha() > 0, shadow.pixelColor(x, y).alpha() > 0)
            if shadow.pixelColor(x, y).alpha() > 0:
                colour = shadow.pixelColor(x, y)
                colours.add(colour.red() == colour.green() == colour.blue())
        self.assertEqual({True}, colours)

    def test_the_cow_is_ankilope_turned_purple(self):
        face = share.face_path("cow")
        ankilope = companion_art.pixmap(face, "ankilope").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        cow = companion_art.pixmap(face, "cow").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        self.assertEqual(ankilope.size(), cow.size())
        self.assertNotEqual(ankilope, cow)

        # Ankilope's tan coat turns a light purple, as CSS hue-rotate(250deg) turns it.
        red, green, blue = companion_art.turn_rgb(companion_art.matrix(250), 234, 171, 91)
        self.assertGreater(blue, green)
        self.assertGreater(red, green)
        art = companion_art.pose_path("ankilope_celebrate")
        turned = companion_art.pixmap(art, "cow").toImage().convertToFormat(QImage.Format.Format_ARGB32)
        plain = QImage(art).convertToFormat(QImage.Format.Format_ARGB32)
        alphas = {(plain.pixelColor(x, 128).alpha(), turned.pixelColor(x, 128).alpha()) for x in range(0, 256, 8)}
        self.assertTrue(all(a == b for a, b in alphas))


if __name__ == "__main__":
    unittest.main()
