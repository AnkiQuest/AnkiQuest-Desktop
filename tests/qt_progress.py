"""Read-only progress, with out-of-order replies and real Qt controls."""
from concurrent.futures import Future
from copy import deepcopy
from http import HTTPStatus
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from aqt.qt import QApplication, QCoreApplication, QEvent, QGridLayout, QPushButton, QToolButton, QWidget
from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
ui = load_in_package("progress_qt", "progress_ui")
ui.tr = lambda text: text


class Progress(unittest.TestCase):
    def setUp(self):
        self.paths, self.tasks = [], []
        self.mw = QWidget()
        self.mw.pm = SimpleNamespace(profile={})
        self.mw.taskman = SimpleNamespace(run_in_background=lambda work, done: self.tasks.append((work, done)))
        self.api = SimpleNamespace(base="https://quest.test", user="sam", token="secret", configured=True, _request=self.request)
        self.addon = SimpleNamespace(mw=self.mw, client=lambda: self.api, open_page=Mock())
        self.window = ui._Progress(self.addon)
        self.window._dialog.show()

    def tearDown(self):
        self.window._close()
        self.mw.close()
        app.processEvents()

    def request(self, path):
        self.paths.append(path)
        if path == "/api/records":
            return [{"window": "day", "unit": "xp", "holders": [{"display": "Sam", "value": 400}]}]
        year = int(path.rsplit("=", 1)[1]) if "=" in path else 2026
        return {"year": year, "years": [2026, 2025], "days": [
            {"date": "%d-01-01" % year, "state": "skipped", "reviews": 0, "time_ms": 0, "xp": 0},
            {"date": "%d-01-02" % year, "state": "met", "reviews": 12, "time_ms": 600_000, "xp": 120},
        ]}

    def finish(self, index=0, error=None):
        work, done = self.tasks.pop(index)
        future = Future()
        if error:
            future.set_exception(error)
        else:
            future.set_result(deepcopy(work()))
        done(future)
        app.processEvents()

    def test_reads_history_and_records_with_distinct_day_states(self):
        self.finish()
        self.finish()
        history = self.window._tables[ui._Section.HISTORY]
        self.assertEqual(2, history.topLevelItemCount())
        self.assertEqual("Streak minimum met", history.topLevelItem(0).text(1))
        self.assertEqual("Skipped day — streak kept", history.topLevelItem(1).text(1))
        self.assertEqual("0 minutes", history.topLevelItem(1).text(3))
        self.assertNotEqual(history.topLevelItem(0).background(1), history.topLevelItem(1).background(1))
        records = self.window._tables[ui._Section.RECORDS]
        self.assertEqual("Sam", records.topLevelItem(0).text(1))
        self.assertEqual(["/api/study/sam", "/api/records"], self.paths)

    def test_a_late_year_reply_cannot_replace_the_selected_year(self):
        self.finish()
        self.finish()
        self.window._years.setCurrentIndex(self.window._years.findData(2025))
        self.window._years.setCurrentIndex(self.window._years.findData(2026))
        self.finish(1)
        self.finish(0)
        table = self.window._tables[ui._Section.HISTORY]
        self.assertEqual("2026-01-02", table.topLevelItem(0).text(0))

    def test_late_replies_do_not_touch_closed_windows_or_another_account(self):
        self.mw.pm.profile = {}
        self.finish()
        self.assertEqual(0, self.window._tables[ui._Section.HISTORY].topLevelItemCount())
        self.window._dialog.close()
        self.finish()

    def test_an_older_server_has_a_clear_fallback_and_retry(self):
        self.finish(error=SimpleServerError(HTTPStatus.NOT_FOUND))
        self.assertIn("does not support", self.window._statuses[ui._Section.HISTORY].text())
        self.assertTrue(self.window._retry[ui._Section.HISTORY].isEnabled())
        button = next(b for b in self.window._dialog.findChildren(QPushButton) if b.text() == "Open website")
        button.click()
        self.addon.open_page.assert_called_once_with("/history")

    def test_an_offline_read_can_be_retried_without_losing_the_other_tab(self):
        self.finish(error=OSError("offline"))
        self.finish()
        self.window._retry[ui._Section.HISTORY].click()
        self.finish()
        self.assertEqual(2, self.window._tables[ui._Section.HISTORY].topLevelItemCount())
        self.assertEqual(1, self.window._tables[ui._Section.RECORDS].topLevelItemCount())

    def test_study_time_reads_the_collection_without_the_server(self):
        self.finish()
        self.finish()
        reads = []
        rows = [(20_000, 90_000), (20_005, 3_000_000)]
        db = SimpleNamespace(all=lambda sql, *args: reads.append(args) or rows)
        self.mw.col = SimpleNamespace(db=db, get_config=lambda key, default: 4)
        with patch.object(ui.time, "time", return_value=20_005 * 86_400 + 43_200), patch.object(ui, "offset_west_min", return_value=0):
            self.window._load_study()
            self.finish()
        values = [self.window._study_values[label].text() for label in ui._STUDY_ROWS]
        self.assertEqual(["50 min", "50 min", "51 min", "51 min", "25 min"], values)
        self.assertEqual("", self.window._study_status.text())
        self.assertEqual([(14_400_000, 20_006 * 86_400_000 + 14_400_000)], reads)
        self.assertEqual(["/api/study/sam", "/api/records"], self.paths)

    def test_study_time_says_when_the_collection_has_no_reviews(self):
        self.mw.col = SimpleNamespace(db=SimpleNamespace(all=lambda sql, *args: []), get_config=lambda key, default: 4)
        self.window._load_study()
        self.finish(len(self.tasks) - 1)
        self.assertEqual("No reviews in this collection yet.", self.window._study_status.text())
        self.assertEqual("0 min", self.window._study_values["Total"].text())

    def study_read(self):
        """Starts a study time read of a collection with 50 minutes today."""
        rows = [(20_005, 3_000_000)]
        self.mw.col = SimpleNamespace(db=SimpleNamespace(all=lambda sql, *args: rows), get_config=lambda key, default: 4)
        with patch.object(ui.time, "time", return_value=20_005 * 86_400 + 43_200), patch.object(ui, "offset_west_min", return_value=0):
            self.window._load_study()
        return len(self.tasks) - 1

    def test_a_study_time_read_from_the_previous_profile_is_ignored(self):
        read = self.study_read()
        self.mw.pm.profile = {}
        self.finish(read)
        self.assertEqual("", self.window._study_values["Total"].text())

    def test_a_study_time_read_from_the_previous_collection_is_ignored(self):
        read = self.study_read()
        self.mw.col = SimpleNamespace(db=SimpleNamespace(all=lambda sql, *args: []), get_config=lambda key, default: 4)
        self.finish(read)
        self.assertEqual("", self.window._study_values["Total"].text())

    def test_no_study_time_read_starts_for_another_profile(self):
        self.mw.pm.profile = {}
        before = len(self.tasks)
        self.study_read()
        self.assertEqual(before, len(self.tasks))

    def test_a_study_time_read_after_closing_changes_nothing(self):
        read = self.study_read()
        self.window._close()
        app.processEvents()
        # The window's labels are gone; the late reply must not touch them.
        self.finish(read)
        self.assertIs(ui._Phase.CLOSED, self.window._phase)

    def test_progress_opens_on_study_time_without_an_account(self):
        home = load_in_package("progress_qt", "home")
        signed_out = SimpleNamespace(base="", user="", token="", configured=False, _request=self.request)
        addon = SimpleNamespace(mw=self.mw, client=lambda: signed_out, open_page=Mock(), open_account=Mock())
        self.paths.clear()
        with patch.object(home, "addon", return_value=addon):
            home.open_progress()
            opened = home.local["progress"]
            try:
                addon.open_account.assert_not_called()
                self.assertIsNotNone(opened)
                self.assertEqual("Study time", opened._tabs.tabText(opened._tabs.currentIndex()))
                # History and Records need an account: they say so and read nothing.
                self.assertEqual([], self.paths)
                for section in (ui._Section.HISTORY, ui._Section.RECORDS):
                    self.assertFalse(opened._tabs.isTabEnabled(opened._tab_index[section]))
            finally:
                home._close_progress()

    def test_browse_has_a_live_entry_and_removes_it_when_closed(self):
        home = load_in_package("progress_qt", "home")
        browser = QWidget()
        browser.form = SimpleNamespace(gridLayout=QGridLayout(browser))
        with patch.object(home, "mw", SimpleNamespace()), patch.object(home, "_toolbar_values", return_value=("AnkiQuest · 7 · Secured", "Open Today")) as labels, patch.object(home, "_open_today") as opened:
            home._browser_entry(browser)
            button = browser.findChild(QToolButton)
            self.assertEqual("AnkiQuest · 7 · Secured", button.text())
            button.click()
            opened.assert_called_once()
            labels.return_value = ("AnkiQuest · Streak unknown", "Open Today")
            home._refresh_toolbar()
            self.assertEqual("AnkiQuest · Streak unknown", button.text())
            browser.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.assertFalse(home.local["browser_buttons"])


class SimpleServerError(Exception):
    def __init__(self, status):
        self.status = status


if __name__ == "__main__":
    unittest.main()
