"""Real Qt checks for the Tools menu's help entries, run by test_qt_windows.py."""

import unittest
from unittest.mock import Mock, patch

from aqt.qt import QMenu, QWidget

from addon_loader import load_in_package
from qt_support import app


help_ui = load_in_package("help_qt", "help_ui")
links = help_ui.links
help_ui.tr = lambda text: text


def entries(menu):
    """The menu's entries as text; a separator is "-", a submenu is its title and its own entries."""
    found = []
    for action in menu.actions():
        if action.isSeparator():
            found.append("-")
        elif action.menu():
            found.append((action.text(), entries(action.menu())))
        else:
            found.append(action.text())
    return found


class HelpMenu(unittest.TestCase):
    def setUp(self):
        # The actions are parented to Anki's main window, as in the add-on; this keeps them alive.
        self.window = QWidget()
        self.menu = QMenu("AnkiQuest", self.window)
        self.rate = help_ui.setup(self.window, self.menu)
        app.clipboard().setText("before")

    def trigger(self, menu, text, opened=True):
        """Triggers the entry `text` and returns the URLs the browser was asked to open."""
        services = Mock()
        services.openUrl.return_value = opened
        with patch.object(help_ui, "QDesktopServices", services), patch.object(help_ui, "tooltip") as tooltip:
            next(action for action in menu.actions() if action.text() == text).trigger()
        self.tooltip = tooltip
        return [call.args[0].toString() for call in services.openUrl.call_args_list]

    def test_entries_follow_androids_about_order(self):
        self.assertEqual(
            ["-", ("Rate AnkiQuest", ["Rate on AnkiWeb", "Star on GitHub"]), "AnkiQuest changelog", "Report a bug"],
            entries(self.menu),
        )

    def test_rate_opens_ankiweb_or_github(self):
        self.assertEqual(["https://ankiweb.net/shared/info/414948448"], self.trigger(self.rate, "Rate on AnkiWeb"))
        self.assertEqual(["https://github.com/AnkiQuest/AnkiQuest-Desktop"], self.trigger(self.rate, "Star on GitHub"))

    def test_report_a_bug_opens_a_new_issue(self):
        self.assertEqual(
            ["https://github.com/AnkiQuest/AnkiQuest-Desktop/issues/new?template=bug_report_form.yml"], self.trigger(self.menu, "Report a bug")
        )
        self.assertEqual("before", app.clipboard().text())
        self.tooltip.assert_not_called()

    def test_a_link_no_browser_opens_is_copied(self):
        self.trigger(self.menu, "Report a bug", opened=False)
        self.assertEqual(links.BUG_FORM, app.clipboard().text())
        self.tooltip.assert_called_once_with("No app can open the link. Link copied.")


if __name__ == "__main__":
    unittest.main()
