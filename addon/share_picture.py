"""Draw supplied sharing text and bundled art locally; never read an account or collection."""

import re

from aqt.qt import (
    QBuffer, QByteArray, QColor, QFont, QImage, QIODevice, QPainter,
    QPalette, QPointF, QRectF, QTextLayout, QTextOption, Qt,
)

from . import companion_art, moods

_WIDTH, _MAX_HEIGHT, _MARGIN = 1080, 4096, 72
_HERO, _GAP = 288, 24
_BRAND, _TITLE, _BODY = 36, 60, 42


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


def render(win, companion, palette, scale=1):
    """A PNG from display content only. Call on the UI thread for bundled companion pixmaps."""
    if not 0 < scale <= 3:
        raise ValueError("Invalid picture font scale")
    pieces = [_words("AnkiQuest", _BRAND * scale, QFont.Weight.Bold)]
    pose = win.get("picture_pose") or "aki_celebrate"
    if pose.startswith("aki_"):
        pose = moods.companion_pose(companion, pose)
    if companion != moods.NONE:
        # Extensions missing from this add-on version fall back to its bundled happy pose.
        fallback = moods.companion_pose(companion, "aki_celebrate")
        for chosen in dict.fromkeys((pose, fallback)):
            if not chosen or not re.fullmatch(r"[a-z0-9_]+", chosen):
                continue
            art = companion_art.pixmap(companion_art.pose_path(chosen), companion, _HERO).toImage()
            if not art.isNull():
                pieces.append((art, _HERO))
                break
    pieces.append(_words(win.get("title", ""), _TITLE * scale, QFont.Weight.Bold))
    body = win.get("picture_body", win.get("body", ""))
    if body:
        pieces.append(_words(body, _BODY * scale, QFont.Weight.Normal))

    height = max(_WIDTH, round(2 * _MARGIN + sum(size + _GAP for _, size in pieces)))
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
        painter.setPen(QColor(palette.color(QPalette.ColorRole.WindowText)))
        top = _MARGIN
        for piece, size in pieces:
            if isinstance(piece, QImage):
                left = (_WIDTH - piece.width()) / 2
                painter.drawImage(QRectF(left, top, piece.width(), piece.height()), piece)
            else:
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
