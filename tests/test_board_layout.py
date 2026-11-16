"""The Today panel laid out by Qt WebEngine, the engine Anki shows it in."""

import json
import os
import unittest

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from aqt.qt import QApplication, QEventLoop, QTimer, QUrl
from aqt.qt import QWebEngineView
from addon_loader import load_in_package

app = QApplication.instance() or QApplication([])
board = load_in_package("board_layout", "board")

# Wide enough for two cards side by side, as in the deck list of a usual Anki window.
WIDTH, HEIGHT = 800, 900
LOAD_TIMEOUT_MS = 20_000

# Each card's right edge, and the rightmost edge of anything inside it.
EDGES = """JSON.stringify([...document.querySelectorAll('#ankiquest .aq-card')].map(card => {
  const inner = card.getBoundingClientRect().right - parseFloat(getComputedStyle(card).borderRightWidth);
  const parts = [...card.querySelectorAll('*')].map(part => part.getBoundingClientRect().right);
  return {card: inner, content: Math.max(...parts)};
}))"""

TODAY = {
    "art": None,
    "mood": None,
    "focus": {"id": 1, "name": "Daily::Spanish — Core 625", "review": 41, "learning": 20, "new": 10,
              "status": "review_now", "label": "71 cards ready", "ready": 71},
    "goal": {"minimum": "Any review today keeps your streak going.", "daily": "Daily goal: 1 of 220 cards", "daily_meter": (1, 220), "backlog": None},
    "board": None,
}


def _wait(signal):
    loop = QEventLoop()
    signal.connect(lambda *_: loop.quit())
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    loop.exec()


def _run(view, script):
    found = []
    loop = QEventLoop()
    view.page().runJavaScript(script, lambda value: (found.append(value), loop.quit()))
    QTimer.singleShot(LOAD_TIMEOUT_MS, loop.quit)
    loop.exec()
    return found[0] if found else None


class TodayLayout(unittest.TestCase):
    def test_the_study_button_stays_inside_its_card(self):
        # Regression: "Study 71 due" stuck out past the right edge of "Your next step".
        page = board.html({"level": 3, "streak": 19, "quests": []}, today=TODAY)
        view = QWebEngineView()
        view.resize(WIDTH, HEIGHT)
        view.setHtml("<!doctype html><html><body>%s</body></html>" % page, QUrl("about:blank"))
        _wait(view.loadFinished)

        edges = json.loads(_run(view, EDGES) or "[]")
        self.assertTrue(edges)
        for edge in edges:
            self.assertLessEqual(edge["content"], edge["card"] + 0.5, edge)
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()
