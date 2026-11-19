"""The AnkiQuest changelog: the installed version's release notes, as on Android's changelog screen."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

from addon_loader import ADDON, load_in_package

release_notes = load_in_package("changelog_notes", "release_notes")


class Html(unittest.TestCase):
    """The same cases as Android's AnkiquestReleaseNotesTest (AnkiQuest-Android#351)."""

    def test_blank_lines_separate_paragraphs(self):
        self.assertEqual("<p>One.</p><p>Two\nlines.</p>", release_notes.html("One.\n\n\nTwo\nlines.\n"))

    def test_bold_text_and_links_are_kept(self):
        self.assertEqual(
            '<p><b>Undo.</b> See <a href="https://example.com/a?b=1&amp;c=2">the notes</a>.</p>',
            release_notes.html("**Undo.** See [the notes](https://example.com/a?b=1&c=2)."),
        )

    def test_markup_in_the_text_is_shown_as_written(self):
        self.assertEqual("<p>a &lt;b&gt; &amp; &quot;c&quot;</p>", release_notes.html('a <b> & "c"'))


class Bundled(unittest.TestCase):
    def test_the_notes_ship_inside_the_addon(self):
        # The packager takes every .md file in addon/, so the notes work offline.
        self.assertEqual(ADDON / "release-notes.md", release_notes.FILE)
        self.assertTrue(release_notes.read().strip())

    def test_the_release_workflow_publishes_the_same_file(self):
        workflow = (ADDON.parent / ".github/workflows/addon.yml").read_text("utf-8")
        self.assertIn("addon/release-notes.md", workflow)


class Dialog(unittest.TestCase):
    def test_the_dialog_with_real_qt(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("qt_changelog.py"))],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
