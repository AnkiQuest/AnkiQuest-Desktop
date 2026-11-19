"""Year/tab -> scoped background read -> table; stale and closed replies do nothing."""
from enum import Enum, auto

import time

from aqt.qt import QBrush, QColor, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, Qt

from . import heatmap_ui, inbox, progress_data, share_ui, study_time, today
from .client import offset_west_min
from .language import tr
from .progress_data import _Section


class _Phase(Enum):
    OPEN = auto()
    CLOSED = auto()


class _Access(Enum):
    """What the window may show: everything for a signed-in account, else only the local tab."""
    ACCOUNT = auto()
    LOCAL = auto()


_COLOURS = {"met": ("#dff1c9", "#254a12"), "short": ("#e9d8a6", "#534619"),
            "frozen": ("#def0ff", "#16527b"), "skipped": ("#def0ff", "#16527b")}
_RECORD_NAMES = {"hour": "Best hour", "day": "Best day", "week": "Best week", "month": "Best month",
                 "year": "Best year", "streak": "Longest streak", "days": "Days studied"}


# The study time tab: its request key, its intro and its rows, in Android's order.
_STUDY = "study_time"
_STUDY_INTRO = ("Time spent answering cards in this collection, uploaded or not. "
                "Days start at Anki’s “Next day starts at” hour, weeks on Monday.")
_STUDY_ROWS = ("Today", "This week", "This month", "Total", "Per study day")


class _Progress:
    def __init__(self, addon):
        self._addon, self._api = addon, addon.client()
        self._profile = addon.mw.pm.profile
        self._phase = _Phase.OPEN
        self._access = _Access.ACCOUNT if self._api.configured else _Access.LOCAL
        self._requests, self._tables, self._statuses, self._retry = {}, {}, {}, {}
        self._dialog = QDialog(addon.mw)
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog.setWindowTitle(tr("Progress"))
        self._dialog.finished.connect(self._finished)
        root = QVBoxLayout(self._dialog)
        tabs = self._tabs = QTabWidget()
        root.addWidget(tabs, 1)
        self._tab_index = {}
        self._years = QComboBox()
        self._years.currentIndexChanged.connect(self._year_changed)
        for section, title, headers in (
            (_Section.HISTORY, tr("History"), [tr("Day"), tr("State"), tr("Reviews"), tr("Study time"), "XP"]),
            (_Section.RECORDS, tr("Records"), [tr("Record"), tr("Player"), tr("Value")]),
        ):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.addWidget(share_ui._plain(tr("Only uploaded study appears here.")))
            controls = QHBoxLayout()
            if section is _Section.HISTORY:
                controls.addWidget(QLabel(tr("Year")))
                controls.addWidget(self._years)
            controls.addStretch(1)
            retry = self._retry[section] = QPushButton(tr("Refresh"))
            retry.clicked.connect(lambda _checked=False, section=section: self._load(section))
            controls.addWidget(retry)
            layout.addLayout(controls)
            status = self._statuses[section] = share_ui._plain("")
            layout.addWidget(status)
            table = self._tables[section] = QTreeWidget()
            table.setHeaderLabels(headers)
            table.setRootIsDecorated(False)
            table.setAlternatingRowColors(True)
            table.setUniformRowHeights(True)
            layout.addWidget(table, 1)
            self._tab_index[section] = tabs.addTab(page, title)
        study = tabs.addTab(self._study_page(), tr("Study time"))
        actions = QHBoxLayout()
        website = QPushButton(tr("Open website"))
        website.clicked.connect(lambda: addon.open_page("/history") if self._owns() else self._close())
        website.setVisible(self._access is _Access.ACCOUNT)
        actions.addWidget(website)
        actions.addStretch(1)
        done = QPushButton(tr("Done"))
        done.clicked.connect(self._dialog.accept)
        actions.addWidget(done)
        root.addLayout(actions)
        screen = self._dialog.screen().availableGeometry()
        self._dialog.resize(min(760, screen.width()), min(640, screen.height()))
        self._load_study()

        # Without an account only Study time, which reads this computer's collection, is open.
        if self._access is _Access.LOCAL:
            for index in self._tab_index.values():
                tabs.setTabEnabled(index, False)
            tabs.setCurrentIndex(study)
            return
        self._load(_Section.HISTORY)
        self._load(_Section.RECORDS)

    def _study_page(self):
        """Study time from this computer's collection; it needs no account or upload."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(share_ui._plain(tr(_STUDY_INTRO)))
        controls = QHBoxLayout()
        controls.addStretch(1)
        self._study_retry = QPushButton(tr("Refresh"))
        self._study_retry.clicked.connect(lambda _checked=False: self._load_study())
        controls.addWidget(self._study_retry)
        layout.addLayout(controls)
        self._study_status = share_ui._plain("")
        layout.addWidget(self._study_status)
        form = QFormLayout()
        self._study_values = {}
        for label in _STUDY_ROWS:
            value = self._study_values[label] = QLabel()
            form.addRow(tr(label), value)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _load_study(self):
        # A read belongs to this window's profile and the collection open when it started.
        if not self._owns_profile():
            self._close()
            return
        col = getattr(self._addon.mw, "col", None)
        if col is None:
            return
        request = self._requests[_STUDY] = object()
        self._study_status.setText(tr("Loading study time…"))
        self._study_retry.setEnabled(False)
        now_ms = int(time.time() * 1000)
        rollover = int(col.get_config("rollover", 4))

        def done(future):
            if not self._owns_profile() or self._requests.get(_STUDY) is not request:
                return
            if getattr(self._addon.mw, "col", None) is not col:
                self._requests.pop(_STUDY)
                self._study_retry.setEnabled(True)
                self._study_status.clear()
                return
            self._requests.pop(_STUDY)
            self._study_retry.setEnabled(True)
            try:
                totals = future.result()
            except Exception as error:
                self._study_status.setText(tr("Could not read study time (%s).") % str(error))
                return
            self._study_status.setText("" if totals.study_days else tr("No reviews in this collection yet."))
            shown = (totals.today_ms, totals.week_ms, totals.month_ms, totals.total_ms, totals.average_ms)
            for label, ms in zip(_STUDY_ROWS, shown):
                self._study_values[label].setText(study_time.duration(ms, tr))

        self._addon.mw.taskman.run_in_background(
            lambda: study_time.load(col.db, now_ms, offset_west_min(), rollover), done)

    def _finished(self, _result):
        self._phase = _Phase.CLOSED
        self._requests.clear()

    def _close(self):
        if self._phase is _Phase.OPEN:
            self._dialog.close()

    def _owns_profile(self):
        return self._phase is _Phase.OPEN and self._profile is self._addon.mw.pm.profile

    def _owns(self):
        return self._owns_profile() and share_ui.same_account(self._api, self._addon.client())

    def current(self):
        """Whether this window still shows what it opened for: its account, or, without one, its
        profile while still signed out."""
        if self._access is _Access.LOCAL:
            return self._owns_profile() and not self._addon.client().configured
        return self._owns()

    def _year_changed(self, _index):
        if self._years.currentData() is not None:
            self._load(_Section.HISTORY)

    def _load(self, section):
        if self._access is _Access.LOCAL:
            return
        if not self._owns():
            self._close()
            return
        request = object()
        self._requests[section] = request
        year = self._years.currentData() if section is _Section.HISTORY else None
        self._tables[section].clear()
        self._statuses[section].setText(tr("Loading progress…"))
        self._retry[section].setEnabled(False)

        def done(future):
            if not self._owns() or self._requests.get(section) is not request:
                return
            self._requests.pop(section)
            self._retry[section].setEnabled(True)
            try:
                data = future.result()
            except Exception as error:
                self._statuses[section].setText(inbox.failure("Could not load progress (%s).", error))
                return
            self._statuses[section].clear()
            if section is _Section.HISTORY:
                self._history(data)
            else:
                self._records(data)
            table = self._tables[section]
            for column in range(table.columnCount()):
                table.resizeColumnToContents(column)

        self._addon.mw.taskman.run_in_background(lambda: progress_data._fetch(self._api, section, year), done)

    def _history(self, data):
        self._years.blockSignals(True)
        self._years.clear()
        current = data.get("year")
        for year in sorted(set(data.get("years", [])) | ({current} if current is not None else set()), reverse=True):
            self._years.addItem(str(year), year)
        self._years.setCurrentIndex(self._years.findData(current))
        self._years.blockSignals(False)
        table = self._tables[_Section.HISTORY]
        for day in sorted(data.get("days", []), key=lambda day: day["date"], reverse=True):
            milliseconds = int(day.get("time_ms", 0))
            duration = today.duration(milliseconds // 60_000, tr) if milliseconds > 0 else tr("%d minutes") % 0
            row = QTreeWidgetItem([day["date"], heatmap_ui._state_label(day.get("state"), tr),
                                  str(day.get("reviews", 0)), duration, str(day.get("xp", 0))])
            colours = _COLOURS.get(day.get("state"))
            if colours:
                row.setBackground(1, QBrush(QColor(colours[0])))
                row.setForeground(1, QBrush(QColor(colours[1])))
            table.addTopLevelItem(row)
        if not table.topLevelItemCount():
            self._statuses[_Section.HISTORY].setText(tr("No uploaded study days yet."))

    def _records(self, data):
        table = self._tables[_Section.RECORDS]
        for record in data:
            name = tr(_RECORD_NAMES.get(record.get("window"), "Record"))
            for holder in record.get("holders", []):
                value = int(holder.get("value", 0))
                unit = tr("%d days") % value if record.get("unit") == "days" else "%d XP" % value
                table.addTopLevelItem(QTreeWidgetItem([name, holder.get("display") or holder.get("user") or "", unit]))
        if not table.topLevelItemCount():
            self._statuses[_Section.RECORDS].setText(tr("No records yet."))
