"""A conquest label stays local until Save; only the server grants an undo window."""

from types import SimpleNamespace
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from addon_loader import load_in_package

conquests = load_in_package("conquest_rules", "conquests")
client = load_in_package("conquest_rules", "client")


class Labels(unittest.TestCase):
    def test_shared_deck_names(self):
        cases = json.loads((Path(__file__).parent / "fixtures/deck_names.json").read_text("utf-8"))["cases"]
        note = SimpleNamespace(fields=["word"], note_type=lambda: {"type": 0})
        card = SimpleNamespace(question=lambda: "word", note=lambda: note, did=5, odid=0)
        for case in cases:
            with self.subTest(path=case["path"]):
                col = SimpleNamespace(db=SimpleNamespace(scalar=lambda *args: 1), get_card=lambda _: card,
                                      decks=SimpleNamespace(name=lambda _: case["path"]))
                self.assertEqual(case["expected"], conquests._local(col, 50)[1])

    def test_shared_front_field_labels(self):
        cases = json.loads((Path(__file__).parent / "fixtures/card_labels.json").read_text("utf-8"))["cases"]
        self.assertTrue(cases)
        for case in cases:
            with self.subTest(case=case["name"]):
                fields = case["fields"]
                note = SimpleNamespace(fields=[value for _, value in fields],
                                       note_type=lambda: {"type": int(case.get("cloze", False)),
                                                          "flds": [{"name": name} for name, _ in fields]})
                card = SimpleNamespace(question=lambda: case["question"], note=lambda: note,
                                       template=lambda: {"qfmt": case["template"]}, did=5, odid=0)
                col = SimpleNamespace(db=SimpleNamespace(scalar=lambda *args: 1),
                                      get_card=lambda _: card,
                                      decks=SimpleNamespace(name=lambda _: "Vocabulary"))
                self.assertEqual(case["expected"], conquests._local(col, 50)[0])

    def test_rendered_front_drops_hidden_content_sounds_and_markup(self):
        front = '<style>.card{color:red}</style><!-- hidden --><script>bad()</script><b>der&nbsp;Hund</b>[sound:dog.mp3][anki:play:q:0]'
        self.assertEqual("der Hund", conquests._suggest(front, ["B1L02", "wrong field"], False))

    def test_cloze_uses_the_text_instead_of_the_rendered_hint(self):
        self.assertEqual("Paris is in France", conquests._suggest("[…] is in France", ["{{c1::Paris::city}} is in {{c2::France}}"], True))

    def test_an_unrenderable_or_identifier_front_falls_back_to_real_words(self):
        for front in ("", "B1L02", "0042", "ID-17", "2024-05-01", "ff12acde"):
            self.assertEqual("the dog", conquests._suggest(front, ["B1L02", "<b>the dog</b>"], False))
        self.assertEqual("", conquests._suggest("", ["B1L02"], False))
        self.assertEqual("", conquests._suggest("<img src=x>", [""], False))
        self.assertEqual(120, len(conquests._suggest("x" * 200, [], False)))

    def test_the_review_finds_its_card_and_home_deck_without_a_request(self):
        note = SimpleNamespace(fields=["B1L02", "Hund"], note_type=lambda: {"type": 0})
        card = SimpleNamespace(question=lambda: "<b>der Hund</b>", note=lambda: note, did=99, odid=5)
        col = SimpleNamespace(db=SimpleNamespace(scalar=Mock(return_value=1)), get_card=Mock(return_value=card),
                              decks=SimpleNamespace(name=Mock(return_value="German")))
        self.assertEqual(("der Hund", "German"), conquests._local(col, 50))
        col.decks.name.assert_called_once_with(5)
        card.question = Mock(side_effect=ValueError("bad template"))
        self.assertEqual("Hund", conquests._local(col, 50)[0])
        col.db.scalar.return_value = None
        self.assertEqual(("", ""), conquests._local(col, 50))


class ConquestApi(unittest.TestCase):
    def setUp(self):
        self.api = SimpleNamespace(base="https://quest.test", user="sam", _request=Mock(return_value={}))

    def test_only_an_explicit_save_posts_the_label(self):
        conquests._load(self.api, 50)
        self.api._request.assert_called_once_with("/api/conquests/sam/50")
        conquests._save(self.api, 50, "  der Hund  ")
        self.api._request.assert_called_with("/api/conquests/sam/50/label", {"label": "der Hund"})
        conquests._save(self.api, 50, "")
        self.api._request.assert_called_with("/api/conquests/sam/50/label", method="DELETE")

    def test_successful_empty_label_responses_are_not_reported_as_errors(self):
        from unittest.mock import patch
        response = BytesIO(b"")
        response.status = 204
        with patch.object(client, "open_url", return_value=response):
            api = client.Client("https://quest.test", "sam", "token")
            self.assertIsNone(conquests._save(api, 50, "der Hund"))

    def test_undo_requires_told_and_a_strictly_future_server_deadline(self):
        for data in ({}, {"told": True}, {"told": False, "undo_until": 101}, {"told": True, "undo_until": 100}):
            self.assertFalse(conquests._can_undo(data, 100))
        self.assertTrue(conquests._can_undo({"told": True, "undo_until": 101}, 100))
        conquests._tell(self.api, 50)
        self.api._request.assert_called_with("/api/conquests/sam/50/tell", {})
        conquests._undo(self.api, 50)
        self.api._request.assert_called_with("/api/conquests/sam/50/tell", method="DELETE")

    def test_share_words_name_the_saved_label_deck_and_page_in_first_person(self):
        found = {"label": "der Hund", "win": 7, "conquest": {"lapses": 5, "answers": 20, "at": 50, "since": 0}}
        win = conquests._win(self.api, 50, found, "German", lambda text: text)
        self.assertEqual(7, win["win"])
        self.assertEqual("I conquered a card!", win["title"])
        self.assertIn("I finally learned “der Hund”, a card I had forgotten 5 times.", win["body"])
        self.assertIn("From my deck “German”.", win["body"])
        self.assertIn("https://quest.test/conquered/sam/50", win["body"])
        self.assertNotIn("None", conquests._win(self.api, 50, {}, "", lambda text: text)["body"])

    def test_shared_picture_words_and_label_privacy(self):
        cases = json.loads((Path(__file__).parent / "fixtures/conquest_share.json").read_text("utf-8"))["cases"]
        for case in cases:
            with self.subTest(case=case["name"]):
                win = conquests._win(self.api, 50, case["found"], case["deck"], str)
                self.assertEqual(case["caption"] + "\nhttps://quest.test/conquered/sam/50", win["body"])
                self.assertEqual(case["picture"], win["picture_body"])
                self.assertNotIn("https://", win["picture_body"])

    def test_conquest_picture_words_have_every_translation(self):
        keys = set()
        for count in (1, 2):
            for label in (None, "saved words"):
                found = {"label": label, "conquest": {"lapses": count, "answers": count, "at": count * 86400000, "since": 0}}
                conquests._win(self.api, 50, found, "My deck", lambda key: keys.add(key) or key)
                conquests._stats(found, lambda key: keys.add(key) or key)
        for code, table in conquests.language.TABLES.items():
            with self.subTest(language=code):
                self.assertFalse(keys - table.keys(), "missing conquest translation")

    def test_shared_days_round_like_android_and_the_website(self):
        cases = json.loads((Path(__file__).parent / "fixtures/conquest_share.json").read_text("utf-8"))["days"]
        for case in cases:
            with self.subTest(elapsed=case["elapsed_ms"]):
                found = {"conquest": {"at": case["elapsed_ms"], "since": 0, "answers": 4, "lapses": 2}}
                days = case["expected"]
                win = conquests._win(self.api, 50, found, "", str)
                self.assertTrue(win["picture_body"].endswith("%d %s to learn" % (days, "day" if days == 1 else "days")))
                self.assertTrue(conquests._stats(found, str).endswith("%d %s to learn" % (days, "day" if days == 1 else "days")))

    def test_stats_pluralize_each_count(self):
        for count, expected in ((1, "1 lapse · 1 answer · 1 day to learn"),
                                (2, "2 lapses · 2 answers · 2 days to learn")):
            with self.subTest(count=count):
                found = {"conquest": {"lapses": count, "answers": count, "at": count * 86400000, "since": 0}}
                self.assertEqual(expected, conquests._stats(found, str))


if __name__ == "__main__":
    unittest.main()
