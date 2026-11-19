"""Rate AnkiQuest, AnkiQuest changelog and Report a bug, as on Android's About screen."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

from addon_loader import load_in_package, load_module

links = load_in_package("help_links", "links")
language = load_module("help_language", "language.py")

# Android's strings for the same entries (AnkiQuest-Android#351, ankiquest_about.xml), except
# where the add-on's pt-PT terms differ.
ANDROID = {
    "ankiquest_rate": ("Rate AnkiQuest", {
        "de": "AnkiQuest bewerten", "es": "Valorar AnkiQuest", "fr": "Évaluer AnkiQuest", "pt": "Avaliar o AnkiQuest",
    }),
    "ankiquest_changelog": ("AnkiQuest changelog", {
        "de": "AnkiQuest-Änderungsprotokoll", "es": "Novedades de AnkiQuest",
        "fr": "Journal des modifications d’AnkiQuest", "pt": "Novidades do AnkiQuest",
    }),
    "ankiquest_all_releases": ("All releases", {
        "de": "Alle Versionen", "es": "Todas las versiones", "fr": "Toutes les versions", "pt": "Todas as versões",
    }),
    "ankiquest_about_report_bug": ("Report a bug", {
        "de": "Fehler melden", "es": "Informar de un error", "fr": "Signaler un bug", "pt": "Comunicar um erro",
    }),
    "ankiquest_link_copied": ("No app can open the link. Link copied.", {
        "de": "Keine App kann den Link öffnen. Link kopiert.",
        "es": "Ninguna app puede abrir el enlace. Enlace copiado.",
        "fr": "Aucune app ne peut ouvrir le lien. Lien copié.",
        # Android's pt says "app" and "link"; the add-on's pt-PT table says "aplicação" and "ligação".
        "pt": "Nenhuma aplicação consegue abrir a ligação. Ligação copiada.",
    }),
}


class Links(unittest.TestCase):
    def test_rate_targets_in_menu_order(self):
        self.assertEqual(
            [("Rate on AnkiWeb", "https://ankiweb.net/shared/info/414948448"),
             ("Star on GitHub", "https://github.com/AnkiQuest/AnkiQuest-Desktop")],
            [(target.title, target.url) for target in links.RateTarget],
        )

    def test_pages_are_in_the_desktop_repository(self):
        self.assertEqual("https://github.com/AnkiQuest/AnkiQuest-Desktop/releases", links.RELEASES)
        self.assertEqual("https://github.com/AnkiQuest/AnkiQuest-Desktop/issues/new?template=bug_report_form.yml", links.BUG_FORM)

    def test_the_bug_form_link_names_a_form_in_this_repository(self):
        template = links.BUG_FORM.split("template=")[1]
        self.assertTrue((Path(__file__).parents[1] / ".github/ISSUE_TEMPLATE" / template).is_file())

    def test_wording_matches_android(self):
        for resource, (source, translations) in ANDROID.items():
            for code, expected in translations.items():
                with self.subTest(resource=resource, language=code):
                    self.assertEqual(expected, language.tr(source, code))


class HelpMenu(unittest.TestCase):
    def test_the_menu_with_real_qt(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("qt_help.py"))],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
