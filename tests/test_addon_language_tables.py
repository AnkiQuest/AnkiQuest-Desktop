"""Every desktop label has a translation in every language, with the same placeholders."""

import ast
import json
import re
import unittest

from addon_loader import ADDON, load_in_package, load_module

PLACEHOLDER = re.compile(r"%[sd]")


def literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return literals(node.body) + literals(node.orelse)
    return []


def labels():
    """Every literal label, including both forms passed to the plural helper."""
    found = set()
    for path in ADDON.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None)
                # language.plural(...) is an attribute call, as in conquests.py.
                helper = name or getattr(node.func, "attr", None)
                count = 2 if helper == "plural" else 1 if name in ("tr", "translate") else 0
                for argument in node.args[:count]:
                    found.update(literals(argument))
    return found


def code_strings():
    """Every string literal in the add-on outside the tables. A label can reach `tr` through
    a variable, as moods.py and inbox.py do, so this is wider than labels()."""
    found = set()
    for path in ADDON.glob("*.py"):
        if path.name != "language.py":
            for node in ast.walk(ast.parse(path.read_text("utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found.add(node.value)
    return found


def table_entries():
    """Every (table, label) pair as written in language.py, so a label written twice shows
    up even though the later entry silently replaces the earlier one at import."""
    found = []
    for node in ast.parse((ADDON / "language.py").read_text("utf-8")).body:
        # TABLE = {...} and TABLE.update({...}).
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            name, table = node.targets[0].id, node.value
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, "attr", None) == "update":
            name, table = node.value.func.value.id, node.value.args[0]
        else:
            continue
        found += [(name, key.value) for key in table.keys]
    return found


def shared_wording():
    return json.loads((ADDON.parent / "tests/fixtures/desktop-wording.json").read_text("utf-8"))["strings"]


language = load_module("aq_language_tables", "language.py")


class TranslationTables(unittest.TestCase):
    def test_shared_screens_match_the_reviewed_android_wording(self):
        for row in shared_wording():
            for code, expected in row["translations"].items():
                with self.subTest(resource=row["android_resource"], language=code):
                    self.assertEqual(expected, language.tr(row["source"], code))

    def test_languages(self):
        self.assertEqual(sorted(language.TABLES), ["de", "es", "fr", "pt"])

    def test_every_language_has_every_key(self):
        keys = set(language.SPANISH)
        for code, table in language.TABLES.items():
            with self.subTest(code=code):
                self.assertEqual(sorted(keys - set(table)), [])
                self.assertEqual(sorted(set(table) - keys), [])

    def test_no_label_is_translated_twice(self):
        entries = table_entries()
        self.assertEqual(sorted({entry for entry in entries if entries.count(entry) > 1}), [])

    def test_every_label_in_the_code_is_translated(self):
        for code, table in language.TABLES.items():
            with self.subTest(code=code):
                self.assertEqual(sorted(labels() - set(table)), [])

    def test_every_translated_label_is_still_in_the_code(self):
        # The shared wording fixture comes from AnkiQuest-Server; its rows stay translated
        # until the fixture drops them, even when no desktop screen shows one any more.
        shared = {row["source"] for row in shared_wording()}
        self.assertEqual(sorted(set(language.SPANISH) - code_strings() - shared), [])

    def test_placeholders_survive_translation(self):
        for code, table in language.TABLES.items():
            for source, text in table.items():
                with self.subTest(code=code, source=source):
                    self.assertEqual(PLACEHOLDER.findall(text), PLACEHOLDER.findall(source))
                    self.assertTrue(text.strip())

    def test_lookup_follows_the_primary_language_and_falls_back_to_english(self):
        self.assertEqual(language.tr("Save", "de_DE"), "Speichern")
        self.assertEqual(language.tr("Save", "pt-BR"), "Guardar")
        self.assertEqual(language.tr("Save", "fr"), "Enregistrer")
        self.assertEqual(language.tr("Save", "es-AR"), "Guardar")
        self.assertEqual(language.tr("Save", "ja"), "Save")
        self.assertEqual(language.tr("Not a label", "de"), "Not a label")

    def test_french_chibi_hint_says_tu_as_on_android(self):
        # Android's ankiquest_companion_chibi_hint in values-fr; French uses "tu".
        self.assertEqual("Tu es à 1 appui de chibi", language.tr("You are 1 tap away from chibi", "fr"))
        self.assertEqual("Tu es à 5 appuis de chibi", language.tr("You are %d taps away from chibi", "fr") % 5)

    def test_french_says_tu(self):
        # French uses informal "tu" on both clients.
        # "vous", "votre", "vos" and the vous imperative ("Choisissez"); "chez" is not a verb.
        formal = re.compile(r"\b(vous|votre|vos|(?!chez\b)\w+ez)\b", re.IGNORECASE)
        for source, text in language.FRENCH.items():
            with self.subTest(source=source):
                self.assertIsNone(formal.search(text), text)

    def test_labels_are_translated_before_names_are_filled_in(self):
        board = load_in_package("aq_language_board", "board")
        spanish = lambda value: language.tr(value, "es-AR")
        self.assertIn("Clasificación", board.html({"level": 4, "streak": 3}, 2, 1, spanish))
        self.assertIn("Puesto 2 esta semana", board.html({}, 2, 0, spanish))
        self.assertEqual("Conectado como Friends::{0}, nivel 2.", spanish("Connected as %s, level %d.") % ("Friends::{0}", 2))


if __name__ == "__main__":
    unittest.main()
