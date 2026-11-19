"""The add-on screenshots in docs/screenshots, rendered from fake data and compared with the committed files.

Each test draws one screen offscreen with the real add-on code: the Today panel in a web view as
Anki's deck list shows it, and the native windows as Qt widgets. Players, server replies, the clock
(2026-11-11 14:26 UTC), fonts (tests/screenshots/fonts only), window sizes and the device pixel
ratio (1) are fixed, so the same Qt build draws the same pixels. A test fails when its picture
differs from the committed one in any pixel.

    QT_QPA_PLATFORM=offscreen python tests/qt_screenshots.py      # compare
    ANKIQUEST_SCREENSHOTS=write python tests/qt_screenshots.py    # write docs/screenshots

The pictures are pinned to the Qt of tests/requirements-anki-26.9.4.txt on Ubuntu 24.04, as CI's
screenshots job runs them. ANKIQUEST_SCREENSHOTS_OUT names a folder for the pictures that differ.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "tests" / "screenshots"
SHOTS = ROOT / "docs" / "screenshots"
FONTS = HERE / "fonts"

# Fontconfig sees only the bundled fonts, so no font on the machine changes a glyph.
_CACHE = tempfile.mkdtemp(prefix="ankiquest-fonts-")
atexit.register(shutil.rmtree, _CACHE, True)
_CONFIG = Path(_CACHE) / "fonts.conf"
_CONFIG.write_text(
    '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
    "<fontconfig><dir>%s</dir><cachedir>%s</cachedir>"
    "<config><rescan><int>0</int></rescan></config></fontconfig>" % (FONTS, _CACHE),
    encoding="utf-8",
)

# Everything that decides pixels, set before Qt starts.
os.environ.update({
    "FONTCONFIG_FILE": str(_CONFIG),
    "QT_QPA_PLATFORM": "offscreen",
    "QT_SCALE_FACTOR": "1",
    "QT_ENABLE_HIGHDPI_SCALING": "0",
    "QT_FONT_DPI": "96",
    "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox --force-device-scale-factor=1 --disable-lcd-text",
    "TZ": "UTC",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
})
os.environ.pop("QT_STYLE_OVERRIDE", None)
import time

time.tzset()

import json
import unittest
from concurrent.futures import Future
from copy import deepcopy
from datetime import date, timedelta
from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(ROOT / "tests"))

from aqt.qt import (
    QApplication, QColor, QCoreApplication, QEventLoop, QFont, QImage, QLocale, QPalette, QStyleFactory, QTimer, QUrl,
    QWidget, Qt,
)
from aqt.qt import QWebEngineView
import anki.lang

from addon_loader import load_in_package

DATA = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
NOW_MS = DATA["clock_ms"]
ME = DATA["player"]
ADDON = ROOT / "addon"

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication.instance() or QApplication(sys.argv[:1])
app.setStyle(QStyleFactory.create("Fusion"))
app.setFont(QFont("Roboto", 10))
# A text cursor that never blinks, so a focused field looks the same at any moment.
app.setCursorFlashTime(0)
QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))

PACKAGE = "screenshots_qt"
board = load_in_package(PACKAGE, "board")
heatmap = load_in_package(PACKAGE, "heatmap")
heatmap_ui = load_in_package(PACKAGE, "heatmap_ui")
moods = load_in_package(PACKAGE, "moods")
progress_ui = load_in_package(PACKAGE, "progress_ui")
social_ui = load_in_package(PACKAGE, "social_ui")
board_ui = load_in_package(PACKAGE, "board_ui")
board_data = load_in_package(PACKAGE, "board_data")
client = load_in_package(PACKAGE, "client")
inbox_ui = load_in_package(PACKAGE, "inbox_ui")
moments_ui = load_in_package(PACKAGE, "moments_ui")
settings_ui = load_in_package(PACKAGE, "ui")
preferences = load_in_package(PACKAGE, "preferences")
language = load_in_package(PACKAGE, "language")


class Theme(Enum):
    LIGHT = "light"
    DARK = "dark"


# Anki's deck list backgrounds, and the window colours of Anki's light and dark themes.
PAGE_BACKGROUND = {Theme.LIGHT: "#ffffff", Theme.DARK: "#202124"}
WINDOW = {Theme.LIGHT: "#efefef", Theme.DARK: "#2b2d31"}

# How long a web view may take to load, the pause between two grabs of it, and how many grabs it
# gets to draw the same picture twice in a row.
LOAD_MS = 20_000
SETTLE_MS = 250
GRABS = 20


def palette(theme):
    """Fusion's light palette, or a dark one in Anki's dark colours."""
    if theme is Theme.LIGHT:
        found = QStyleFactory.create("Fusion").standardPalette()
        found.setColor(QPalette.ColorRole.Window, QColor(WINDOW[theme]))
        return found
    found = QPalette()
    colours = {
        QPalette.ColorRole.Window: WINDOW[theme], QPalette.ColorRole.WindowText: "#f2f3f5",
        QPalette.ColorRole.Base: "#1e1f22", QPalette.ColorRole.AlternateBase: "#26282c",
        QPalette.ColorRole.Text: "#f2f3f5", QPalette.ColorRole.Button: "#383a40",
        QPalette.ColorRole.ButtonText: "#f2f3f5", QPalette.ColorRole.Highlight: "#2f7fc1",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: "#1e1f22",
        QPalette.ColorRole.ToolTipText: "#f2f3f5", QPalette.ColorRole.PlaceholderText: "#8e9297",
        QPalette.ColorRole.Light: "#4a4d55", QPalette.ColorRole.Midlight: "#3c3f45",
        QPalette.ColorRole.Mid: "#25272b", QPalette.ColorRole.Dark: "#1a1b1e", QPalette.ColorRole.Shadow: "#000000",
        QPalette.ColorRole.Link: "#5aa9e6",
    }
    for role, colour in colours.items():
        found.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        found.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6d7178"))
    return found


def settle():
    for _ in range(5):
        app.processEvents()


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


# Requests data.json has no reply for. The add-on shows most failures as a status line, so the
# screen is checked for them after drawing.
MISSES = []


class Server:
    """Answers the add-on's reads from data.json; anything else is recorded as a miss."""

    def __init__(self):
        self.replies = deepcopy(DATA["server"])

    def request(self, path, body=None, method=None):
        route = urlsplit(path).path
        if body is None and method is None and route in self.replies:
            return deepcopy(self.replies[route])
        MISSES.append(path)
        raise AssertionError("no fake reply for %s" % path)


def run_now(work, done, uses_collection=False):
    """The add-on's background tasks, run at once so a screen is complete when it opens."""
    future = Future()
    try:
        future.set_result(work())
    except Exception as error:
        future.set_exception(error)
    done(future)


def main_window():
    mw = QWidget()
    mw.pm = SimpleNamespace(profile={})
    mw.taskman = SimpleNamespace(run_in_background=run_now)
    return mw


def api(server):
    found = client.Client("https://ankiquest.example", ME, "token")
    found._request = server.request
    return found


# Today panel ------------------------------------------------------------------------------

def view(name):
    """A Today view from data.json, with the tuples and enums board.html reads."""
    found = deepcopy(DATA["today"][name])
    today = found["view"]
    goal = today.get("goal") or {}
    for key in ("minimum_meter", "daily_meter"):
        if goal.get(key) is not None:
            goal[key] = tuple(goal[key])
    standing = today.get("board")
    if standing:
        standing["rows"] = [tuple(row) for row in standing["rows"]]
        standing["scopes"] = [tuple(scope) for scope in standing.get("scopes", [["friends", "Friends"]])]
    return found["profile"], today, moods.Flame(found["flame"])


def heatmap_html(name):
    """The review heatmap under the panel: a fixed review history ending on the clock's day."""
    spec = DATA["heatmap"][name]
    today = date.fromisoformat(spec["today"])
    reviews = {today - timedelta(days=int(back)): count for back, count in spec["reviews"].items()}
    scheduled = {today + timedelta(days=int(ahead)): count for ahead, count in spec["scheduled"].items()}
    verdicts = {today - timedelta(days=int(back)): heatmap.Verdict(state) for back, state in spec["verdicts"].items()}
    data = heatmap.summarize(today, reviews, scheduled, verdicts=verdicts)
    return heatmap_ui.html(data, language.tr, "en", True, spec.get("art"))


def page(body, theme):
    night = " class='nightMode night_mode'" if theme is Theme.DARK else ""
    colour = "#f2f3f5" if theme is Theme.DARK else "#000000"
    return (
        "<!doctype html><html><head><meta charset=utf-8><style>"
        "html,body{margin:0;background:%s;color:%s;font-family:Roboto;overflow:hidden}"
        "body{padding:12px 8px}"
        "</style></head><body%s>%s</body></html>"
    ) % (PAGE_BACKGROUND[theme], colour, night, body)


def render_page(html, width):
    """Loads `html` in a web view `width` pixels wide and grabs the whole page."""
    web = QWebEngineView()
    web.resize(width, 400)
    web.show()
    loop = QEventLoop()
    loaded = []
    web.loadFinished.connect(lambda ok: (loaded.append(ok), loop.quit()))
    QTimer.singleShot(LOAD_MS, loop.quit)
    web.setHtml(html, QUrl.fromLocalFile(str(ADDON) + "/"))
    loop.exec()
    if loaded != [True]:
        raise AssertionError("the page did not load")
    wait(SETTLE_MS)

    # Resize to the page's height, then grab once it has drawn again.
    heights = []
    web.page().runJavaScript("document.documentElement.scrollHeight", 0, lambda value: (heights.append(value), loop.quit()))
    loop.exec()
    web.resize(width, int(heights[0]))
    image = steady(web)
    web.close()
    web.deleteLater()
    settle()
    return image


def steady(web):
    """The web view's picture once two grabs in a row agree: Chromium paints in its own time."""
    previous = None
    for _ in range(GRABS):
        wait(SETTLE_MS)
        image = web.grab().toImage()
        if image == previous:
            return image
        previous = image
    raise AssertionError("the page kept changing")


def today_screen(name, theme, width, with_heatmap=False):
    def draw():
        profile, today, flame = view(name)
        body = board.html(profile, None, today.pop("unread", 0), language.tr, None, today, flame=flame)
        # The upload line the add-on writes under the panel.
        body += '<p style="text-align:center;font-size:12px">%s</p>' % preferences.last_upload_text(DATA["last_upload_ms"])
        if with_heatmap:
            body += heatmap_html(name)
        return render_page(page(body, theme), width)
    return draw


# Native windows ---------------------------------------------------------------------------

def grab(dialog, size):
    dialog.resize(*size)
    dialog.show()
    settle()
    return dialog.grab().toImage()


def progress_screen(size):
    def draw():
        mw = main_window()
        addon = SimpleNamespace(mw=mw, client=lambda: api(Server()), open_page=Mock())
        window = progress_ui._Progress(addon)
        image = grab(window._dialog, size)
        window._close()
        return image
    return draw


def social_screen(size, tab):
    def draw():
        mw = main_window()
        found = api(Server())
        addon = SimpleNamespace(mw=mw, client=lambda: found)
        window = social_ui._Window(addon, Mock())
        tabs = window._dialog.findChild(social_ui.QTabWidget)
        tabs.setCurrentIndex(tab)
        if tab == 0:
            tree = window._people_tree
            tree.setCurrentItem(tree.topLevelItem(1).child(0))
        if tab == 1:
            window._invite_field.setText(DATA["invite"])
            window._preview_invite()
        if tab == 2:
            goals = window._goals
            goals._table.setCurrentItem(goals._table.topLevelItem(0))
        image = grab(window._dialog, size)
        window._close()
        return image
    return draw


def board_window_screen(size):
    def draw():
        mw = main_window()
        found = api(Server())
        found.server_info = Mock(return_value=(frozenset({"global_leaderboard_hide"}), None))
        addon = SimpleNamespace(mw=mw, client=lambda: found)
        pictures = SimpleNamespace(_get=Mock(return_value=None), _load=Mock())
        board_data._remember(mw.pm.profile, found, board_data._Query("week", "global"))
        window = board_ui._Window(addon, pictures, Mock())
        image = grab(window._dialog, size)
        window._close()
        return image
    return draw


def inbox_screen(size):
    def draw():
        parent = main_window()
        found = api(Server())
        dialog = inbox_ui._build(parent, found, "aki", lambda: found, run_now, Mock(), Mock())
        dialog.reload()
        image = grab(dialog, size)
        dialog.close()
        return image
    return draw


def goal_create_screen(size):
    def draw():
        mw = main_window()
        found = api(Server())
        window = social_ui._Window(SimpleNamespace(mw=mw, client=lambda: found), Mock())
        goals = window._goals
        goals._new()
        creator = goals._creator
        creator._recipients.item(0).setCheckState(Qt.CheckState.Checked)
        image = grab(creator._dialog, size)
        window._close()
        return image
    return draw


def moment_addon(mw, found):
    """The add-on parts a moment card calls: a German card for a conquest, Aki, no saved choices."""
    note = SimpleNamespace(fields=["B1L02", "Hund"], note_type=lambda: {"type": 0})
    card = SimpleNamespace(question=lambda: "<b>der Hund</b>", note=lambda: note, did=5, odid=0)
    mw.state = "overview"
    mw.col = SimpleNamespace(db=SimpleNamespace(scalar=lambda *args: 1), get_card=lambda cid: card,
                             decks=SimpleNamespace(name=lambda did: "German"))
    session_day = DATA["moments"]["session_day"]
    return SimpleNamespace(
        mw=mw, client=lambda: found, current_companion=lambda: "aki", config=lambda: {}, save_config=Mock(),
        redraw=Mock(), open_inbox=Mock(),
        home=SimpleNamespace(open_progress=Mock(), continue_studying=Mock(),
                             _streak_title=Mock(return_value="Streak secured!"),
                             _session_day=Mock(return_value=session_day)),
    )


def moment_screen(size, name):
    def draw():
        mw = main_window()
        found = SimpleNamespace(configured=True, base="https://ankiquest.example", user=ME, name=ME, token="token",
                                deck_settings=lambda: {"celebrations": True}, _request=Server().request)
        addon = moment_addon(mw, found)
        spec = DATA["moments"][name]
        card = moments_ui._Card(addon, found, mw.pm.profile, spec["items"], spec.get("summary"))
        image = grab(card._dialog, size)
        card._dialog.close()
        return image
    return draw


def settings_screen(size, language):
    def draw():
        server = Server()
        found = SimpleNamespace(configured=True, user=ME, _request=server.request,
                                deck_settings=lambda: server.request("/api/decks/" + ME),
                                companion=lambda: "ankilope", set_companion=Mock())
        mw = SimpleNamespace(pm=SimpleNamespace(profile={}), taskman=SimpleNamespace(run_in_background=run_now))
        config = {"url": "https://ankiquest.example", "user": ME, "token": "token"}
        images = []

        def capture():
            dialog = app.activeModalWidget()
            dialog.resize(*size)
            settle()

            # Scroll so the reminders are in view.
            scroll = dialog.findChild(settings_ui.QScrollArea, "ankiquest_settings_scroll")
            notify = [group for group in dialog.findChildren(settings_ui.QGroupBox) if group.title() == settings_ui.tr("Notify me about")]
            scroll.verticalScrollBar().setValue(notify[0].y() - 6)
            settle()
            images.append(dialog.grab().toImage())
            dialog.reject()

        QTimer.singleShot(0, capture)
        with patch.object(anki.lang, "current_lang", language):
            settings_ui.settings_dialog(
                None, config, Mock(), Mock(), companion="ankilope", on_account=Mock(),
                extra=lambda dialog, groups: preferences.section(dialog, groups, mw, found),
            )
        return images[0]
    return draw


# Name, theme, drawing. Names are the files in docs/screenshots without "desktop-" and ".png".
SCREENS = {
    "today-light": (Theme.LIGHT, today_screen("today", Theme.LIGHT, 480)),
    "today-dark": (Theme.DARK, today_screen("today", Theme.DARK, 360)),
    "day-light": (Theme.LIGHT, today_screen("day", Theme.LIGHT, 480, with_heatmap=True)),
    "day-dark": (Theme.DARK, today_screen("day", Theme.DARK, 360, with_heatmap=True)),
    "boards-light": (Theme.LIGHT, today_screen("boards", Theme.LIGHT, 480)),
    "boards-dark": (Theme.DARK, today_screen("boards", Theme.DARK, 360)),
    "board-window": (Theme.LIGHT, board_window_screen((640, 420))),
    "board-window-dark": (Theme.DARK, board_window_screen((360, 420))),
    "progress": (Theme.LIGHT, progress_screen((640, 520))),
    "progress-dark": (Theme.DARK, progress_screen((360, 520))),
    "friends": (Theme.LIGHT, social_screen((640, 580), 0)),
    "groups": (Theme.LIGHT, social_screen((640, 580), 1)),
    "friend-goals": (Theme.DARK, social_screen((640, 580), 2)),
    "friend-goal-create": (Theme.DARK, goal_create_screen((460, 500))),
    "inbox": (Theme.LIGHT, inbox_screen((640, 640))),
    "inbox-dark": (Theme.DARK, inbox_screen((480, 640))),
    "moments": (Theme.LIGHT, moment_screen((480, 640), "session")),
    "conquest": (Theme.LIGHT, moment_screen((480, 640), "conquest")),
    "reminders-en": (Theme.DARK, settings_screen((640, 640), "en")),
    "reminders-de": (Theme.DARK, settings_screen((640, 640), "de")),
}


class Mode(Enum):
    COMPARE = "compare"
    WRITE = "write"


MODE = Mode(os.environ.get("ANKIQUEST_SCREENSHOTS", Mode.COMPARE.value))
OUT = os.environ.get("ANKIQUEST_SCREENSHOTS_OUT")


def draw(name):
    theme, drawing = SCREENS[name]
    app.setPalette(palette(theme))
    MISSES.clear()
    with patch("time.time", return_value=NOW_MS / 1000), patch.object(anki.lang, "current_lang", "en"):
        image = drawing()
    if MISSES:
        raise AssertionError("tests/screenshots/data.json has no reply for %s" % ", ".join(MISSES))
    return image.convertToFormat(QImage.Format.Format_RGB32)


def differences(image, committed):
    """How many pixels differ, and the largest channel difference."""
    if image.size() != committed.size():
        return image.width() * image.height(), 255
    count, worst = 0, 0
    for y in range(image.height()):
        for x in range(image.width()):
            a, b = image.pixel(x, y), committed.pixel(x, y)
            if a != b:
                count += 1
                worst = max(worst, *(abs(((a >> s) & 255) - ((b >> s) & 255)) for s in (0, 8, 16)))
    return count, worst


class Screenshots(unittest.TestCase):
    def check(self, name):
        image = draw(name)
        path = SHOTS / ("desktop-%s.png" % name)
        if MODE is Mode.WRITE:
            self.assertTrue(image.save(str(path), "PNG", 0), path)
            return
        committed = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB32)
        if image == committed:
            return
        if OUT:
            Path(OUT).mkdir(parents=True, exist_ok=True)
            image.save(str(Path(OUT) / path.name), "PNG", 0)
        count, worst = differences(image, committed)
        self.fail("%s differs from the drawing in %d pixels (largest channel difference %d): "
                  "run ANKIQUEST_SCREENSHOTS=write python tests/qt_screenshots.py" % (path.name, count, worst))


def _test(name):
    return lambda self: self.check(name)


for _name in SCREENS:
    setattr(Screenshots, "test_" + _name.replace("-", "_"), _test(_name))


if __name__ == "__main__":
    unittest.main()
