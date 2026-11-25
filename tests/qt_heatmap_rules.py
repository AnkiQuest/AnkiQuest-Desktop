"""The heatmap's colour levels from the shared rules' WebAssembly module, run in Qt WebEngine,
the engine Anki shows the deck list in. Runs in its own process (test_qt_windows.py): WebEngine
needs a QApplication it was set up for. Needs the module (package-addon rules)."""

import json
import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from aqt.qt import QApplication, QCoreApplication, QEventLoop, Qt, QTimer, QUrl
from aqt.qt import QWebEngineView
from PyQt6.QtQuick import QQuickWindow, QSGRendererInterface
from addon_loader import load_in_package

# Software rendering, as Anki's own software option does: CI has no GL context.
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
app = QApplication([sys.argv[0]])

rules = load_in_package("heatmap_rules", "rules")
heatmap = load_in_package("heatmap_rules", "heatmap")
heatmap_ui = load_in_package("heatmap_rules", "heatmap_ui")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "review_heatmap.json"
LOAD_TIMEOUT_MS = 20_000
POLL_MS = 50
TODAY = date(2024, 3, 1)


def _page(body):
    view = QWebEngineView()
    loop = QEventLoop()
    view.loadFinished.connect(lambda *_: loop.quit())
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    view.setHtml("<!doctype html><html><body>%s</body></html>" % body, QUrl("about:blank"))
    loop.exec()
    return view


def _run(view, script):
    found = []
    loop = QEventLoop()
    view.page().runJavaScript(script, lambda value: (found.append(value), loop.quit()))
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    loop.exec()
    return found[0] if found else None


def _until(view, script):
    """`script`'s value once it is not null: the module compiles asynchronously."""
    for _ in range(LOAD_TIMEOUT_MS // POLL_MS):
        value = _run(view, script)
        if value is not None:
            return value
        loop = QEventLoop()
        QTimer.singleShot(POLL_MS, loop.quit)
        loop.exec()
    return None


class Levels(unittest.TestCase):
    def test_every_intensity_case_through_the_pages_loader(self):
        cases = json.loads(FIXTURE.read_text("utf-8"))["intensity_cases"]
        self.assertTrue(cases)
        script = (
            "<script>window.levels=null;var cases=%s;%s.then(function(r){"
            "window.levels=JSON.stringify(cases.map(function(c){return c.counts.map(function(n){"
            "return r.heatmap_intensity(n,c.daily_average);});}));},"
            "function(e){window.levels=JSON.stringify(String(e));});</script>"
        ) % (json.dumps(cases), rules.promise())
        view = _page(script)
        levels = json.loads(_until(view, "window.levels") or "null")
        self.assertEqual([case["levels"] for case in cases], levels)
        view.deleteLater()

    def test_the_heatmap_draws_each_day_at_its_level(self):
        day = lambda offset: TODAY + timedelta(days=offset)
        data = heatmap.summarize(
            TODAY, {day(0): 10, day(-1): 30, day(-3): 5}, {day(1): 4, day(2): 50}, {day(-2)},
            {day(-3): heatmap.Verdict(heatmap.SHORT, 1, 10)},
        )
        view = _page(heatmap_ui.html(data, lambda text: text))
        self.assertEqual("1", _until(view, "document.getElementById('aq-heatmap').dataset.ready || null"))
        classes = json.loads(_run(view, """JSON.stringify(Object.fromEntries([...document.querySelectorAll(
            '#aq-heatmap .hm-grid button')].map(b => [b.dataset.day, b.className])))"""))
        # The average is 15 reviews per study day.
        # Today is selected when the page opens.
        self.assertEqual("l2 today sel", classes["2024-03-01"])
        self.assertEqual("l3", classes["2024-02-29"])
        self.assertEqual("l0 k", classes["2024-02-28"])
        self.assertEqual("s", classes["2024-02-27"])
        self.assertEqual("f1", classes["2024-03-02"])
        self.assertEqual("f4", classes["2024-03-03"])
        view.deleteLater()


if __name__ == "__main__":
    # Leave without tearing down WebEngine, which can crash on exit with software rendering.
    passed = unittest.main(exit=False).result.wasSuccessful()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if passed else 1)
