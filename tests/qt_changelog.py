"""Real Qt checks for the AnkiQuest changelog dialog, run by test_qt_windows.py."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from aqt.qt import QMenu, QPushButton, QTextBrowser, QUrl, QWidget

from addon_loader import load_in_package
from qt_support import app


help_ui = load_in_package("changelog_qt", "help_ui")
links = help_ui.links
help_ui.tr = lambda text: text

NOTES = "**Undo.** See [the notes](https://example.com/notes)."


class Changelog(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.notes = Path(self.folder.name) / "release-notes.md"
        self.notes.write_text(NOTES, "utf-8")

    def tearDown(self):
        self.window.close()
        app.processEvents()

    def dialog(self, version=None):
        """The dialog for an add-on folder holding `version` as its version.json (none: a local copy)."""
        if version is not None:
            (Path(self.folder.name) / "version.json").write_text(json.dumps(version), "utf-8")
        with patch.object(help_ui.release_notes, "FILE", self.notes):
            dialog = help_ui.changelog(self.window, Path(self.folder.name))
        self.addCleanup(dialog.close)
        return dialog

    def opened(self, action):
        """Runs `action` and returns the URLs the browser was asked to open."""
        services = Mock()
        services.openUrl.return_value = True
        with patch.object(help_ui, "QDesktopServices", services), patch.object(help_ui, "tooltip"):
            action()
        return [call.args[0].toString() for call in services.openUrl.call_args_list]

    def buttons(self, dialog):
        return [button.text() for button in dialog.findChildren(QPushButton)]

    def test_the_title_is_androids(self):
        self.assertEqual("AnkiQuest changelog", self.dialog().windowTitle())

    def test_it_names_the_installed_release(self):
        dialog = self.dialog({"release": 15, "nightly": 0, "commit": "abc"})
        self.assertEqual("addon-15", dialog.findChild(QWidget, "ankiquest_changelog_release").text())

    def test_a_local_copy_says_so(self):
        dialog = self.dialog()
        self.assertEqual("Local copy", dialog.findChild(QWidget, "ankiquest_changelog_release").text())

    def test_it_shows_the_bundled_notes(self):
        text = self.dialog().findChild(QTextBrowser).toPlainText()
        self.assertEqual("Undo. See the notes.", text.strip())

    def test_buttons_follow_androids_order(self):
        self.assertEqual(["All releases", "Rate AnkiQuest"], self.buttons(self.dialog()))

    def test_all_releases_opens_the_releases(self):
        button = self.dialog().findChild(QPushButton, "ankiquest_changelog_releases")
        self.assertEqual([links.RELEASES], self.opened(button.click))

    def test_rate_offers_ankiweb_and_github(self):
        menu = self.dialog().findChild(QPushButton, "ankiquest_changelog_rate").menu()
        self.assertEqual(["Rate on AnkiWeb", "Star on GitHub"], [action.text() for action in menu.actions()])
        self.assertEqual([links.ANKIWEB], self.opened(menu.actions()[0].trigger))
        self.assertEqual([links.REPOSITORY], self.opened(menu.actions()[1].trigger))

    def test_a_link_in_the_notes_opens_in_the_browser(self):
        notes = self.dialog().findChild(QTextBrowser)
        self.assertFalse(notes.openLinks())
        url = QUrl("https://example.com/notes")
        self.assertEqual(["https://example.com/notes"], self.opened(lambda: notes.anchorClicked.emit(url)))


class Menu(unittest.TestCase):
    def test_the_menu_entry_opens_the_dialog_not_the_browser(self):
        window = QWidget()
        menu = QMenu("AnkiQuest", window)
        help_ui.setup(window, menu)
        entry = next(action for action in menu.actions() if action.text() == "AnkiQuest changelog")
        services = Mock()
        with patch.object(help_ui, "QDesktopServices", services), patch.object(help_ui, "changelog") as changelog:
            entry.trigger()
        changelog.assert_called_once_with(window, help_ui.ADDON_DIR)
        services.openUrl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
