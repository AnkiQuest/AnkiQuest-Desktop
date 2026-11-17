"""Draw supplied sharing text and bundled art locally; never read an account or collection."""

import re

from aqt.qt import (
    QBuffer, QByteArray, QColor, QFont, QFontMetricsF, QImage, QIODevice, QLinearGradient, QPainter,
    QPalette, QPointF, QRectF, QTextLayout, QTextOption, Qt,
)

from . import companion_art, moods, share
from .language import _locale, plural

_WIDTH, _MAX_HEIGHT, _MARGIN = 1080, 4096, 72
_HERO, _GAP = 288, 24
_BRAND, _TITLE, _BODY = 36, 60, 42
_STREAK_HERO, _NUMBER = 400, 240
_GOLD, _WHITE = "#FFD54F", "#FFFFFF"
_MILESTONES = (7, 30, 100, 365)
# Gradients only; moods.HEAT owns the thresholds and selects the pose.
_HEAT_COLORS = {
    "aki_streak": ("#B45309", "#92400E"),
    "aki_streak_hot": ("#C2410C", "#B91C1C"),
    "aki_streak_blazing": ("#DC2626", "#7F1D1D"),
    "aki_streak_legend": ("#B91C1C", "#581C87"),
}


def _words(text, size, weight):
    font = QFont()
    font.setPixelSize(round(size))
    font.setWeight(weight)
    # QTextLayout treats a line separator as a hard break, while wrapping long words too.
    layout = QTextLayout(str(text).replace("\n", "\u2028"), font)
    option = QTextOption(Qt.AlignmentFlag.AlignHCenter)
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    height = 0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(_WIDTH - 2 * _MARGIN)
        line.setPosition(QPointF(0, height))
        height += line.height()
        if height > _MAX_HEIGHT:
            layout.endLayout()
            raise ValueError("The share card is too tall")
    layout.endLayout()
    return layout, height


def _text(value, size, weight, ink):
    return (*_words(value, size, weight), ink)


def _art(companion, pose, size, fallback="aki_celebrate"):
    if pose.startswith("aki_"):
        pose = moods.companion_pose(companion, pose)
    if companion != moods.NONE:
        # A missing streak tier uses its core streak pose before the generic happy fallback.
        fallbacks = (moods.companion_pose(companion, fallback), moods.companion_pose(companion, "aki_celebrate"))
        for chosen in dict.fromkeys((pose, *fallbacks)):
            if not chosen or not re.fullmatch(r"[a-z0-9_]+", chosen):
                continue
            art = companion_art.pixmap(companion_art.pose_path(chosen), companion, size).toImage()
            if not art.isNull():
                return art, size, None
    return None


def _plain(win, companion, ink, scale):
    pieces = [_text("AnkiQuest", _BRAND * scale, QFont.Weight.Bold, ink)]
    art = _art(companion, win.get("picture_pose") or "aki_celebrate", _HERO)
    if art is not None:
        pieces.append(art)
    pieces.append(_text(win.get("title", ""), _TITLE * scale, QFont.Weight.Bold, ink))
    body = win.get("picture_body", win.get("body", ""))
    if body:
        pieces.append(_text(body, _BODY * scale, QFont.Weight.Normal, ink))
    return pieces


def _streak_unit(count):
    # English has one unit for both counts; the other languages keep their reviewed plurals.
    unit = plural("streak day", "streak days", count)
    return "day streak" if unit in ("streak day", "streak days") else unit


def _fiery(win, companion, streak, scale):
    pieces = [_text("AnkiQuest", _BRAND * scale, QFont.Weight.Bold, _WHITE)]
    art = _art(companion, moods.streak_pose(moods.FIRE, streak), _STREAK_HERO, "aki_streak")
    if art is not None:
        pieces.append(art)
    # The number fits one line and is already large; only the other text follows font scale.
    number = _locale().toString(streak)
    font = QFont()
    font.setPixelSize(_NUMBER)
    font.setWeight(QFont.Weight.Black)
    width = QFontMetricsF(font).horizontalAdvance(number)
    size = min(_NUMBER, int(_NUMBER * (_WIDTH - 2 * _MARGIN) / max(1, width)))
    pieces.append(_text(number, size, QFont.Weight.Black, _GOLD))
    days = _streak_unit(streak)
    pieces.append(_text(days, _TITLE * scale, QFont.Weight.Bold, _GOLD))
    pieces.append(_text(win.get("title", ""), _TITLE * scale, QFont.Weight.Bold, _WHITE))
    body = win.get("picture_body", win.get("body", ""))
    if body.strip() and body != "%s %s" % (number, days):
        pieces.append(_text(body, _BODY * scale, QFont.Weight.Normal, _WHITE))
    milestone = next((day for day in _MILESTONES if day > streak), None)
    if milestone is not None:
        remaining = milestone - streak
        line = plural("%s day to %s", "%s days to %s", remaining) % (_locale().toString(remaining), _locale().toString(milestone))
        pieces.append(_text(line, _BODY * scale, QFont.Weight.Bold, _WHITE))
    return pieces


def render(win, companion, palette, scale=1):
    """A PNG from display content only. Call on the UI thread for bundled companion pixmaps."""
    if not 0 < scale <= 3:
        raise ValueError("Invalid picture font scale")
    streak = win.get("picture_streak")
    if streak is not None and (type(streak) is not int or not 0 < streak <= share.MAX_STREAK):
        raise ValueError("Invalid picture streak")
    pieces = (_plain(win, companion, palette.color(QPalette.ColorRole.WindowText), scale) if streak is None
              else _fiery(win, companion, streak, scale))

    content = sum(size + _GAP for _, size, _ in pieces)
    height = max(_WIDTH, round(2 * _MARGIN + content))
    if height > _MAX_HEIGHT:
        raise ValueError("The share card is too tall")
    image = QImage(_WIDTH, height, QImage.Format.Format_ARGB32)
    if image.isNull():
        raise MemoryError("Could not allocate the share picture")
    image.fill(palette.color(QPalette.ColorRole.Window))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if streak is not None:
            colors = _HEAT_COLORS[moods.streak_pose(moods.FIRE, streak)]
            gradient = QLinearGradient(0, 0, 0, height - 1)
            gradient.setColorAt(0, QColor(colors[0]))
            gradient.setColorAt(1, QColor(colors[1]))
            painter.fillRect(image.rect(), gradient)
        top = _MARGIN if streak is None else (height - content + _GAP) / 2
        for piece, size, ink in pieces:
            if isinstance(piece, QImage):
                left = (_WIDTH - piece.width()) / 2
                painter.drawImage(QRectF(left, top, piece.width(), piece.height()), piece)
            else:
                painter.setPen(QColor(ink))
                piece.draw(painter, QPointF(_MARGIN, top))
            top += size + _GAP
    finally:
        painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("Could not encode the share picture")
    return {"png": bytes(data)}
