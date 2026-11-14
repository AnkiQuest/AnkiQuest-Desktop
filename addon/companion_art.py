"""The companion's bundled art as Qt pictures.

The cow has no art yet (#88). Until it has, its pictures are Ankilope's, hue-rotated by
`moods.hue_degrees` with the colour matrix CSS hue-rotate() uses, so Qt and web views match."""

import math
from pathlib import Path

from aqt.qt import QIcon, QImage, QPixmap, Qt

from . import moods
from .share import face_path

_ADDON = Path(__file__).resolve().parent

# Turned images by (file, degrees); turning one takes a moment, so it happens once.
_TURNED = {}


def pose_path(pose):
    """The bundled file of a pose such as `aki_streak`."""
    return str(_ADDON / "art" / (pose + ".png"))


def pixmap(path, companion, size=None):
    """The picture at `path` as `companion` shows it, scaled to fit `size` pixels if given."""
    picture = QPixmap.fromImage(_image(path, moods.hue_degrees(companion)))
    if size is None:
        return picture
    return picture.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


def icon(companion):
    """`companion`'s face as a window or tray icon; an empty icon for no companion."""
    path = face_path(companion)
    return QIcon(pixmap(path, companion)) if path else QIcon()


def _image(path, degrees):
    if not degrees:
        return QImage(path)
    key = (path, degrees)
    if key not in _TURNED:
        _TURNED[key] = _turn(QImage(path), degrees)
    return _TURNED[key]


def matrix(degrees):
    """The colour matrix of CSS hue-rotate(`degrees`) (Filter Effects, feColorMatrix)."""
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return (
        (0.213 + cos * 0.787 - sin * 0.213, 0.715 - cos * 0.715 - sin * 0.715, 0.072 - cos * 0.072 + sin * 0.928),
        (0.213 - cos * 0.213 + sin * 0.143, 0.715 + cos * 0.285 + sin * 0.140, 0.072 - cos * 0.072 - sin * 0.283),
        (0.213 - cos * 0.213 - sin * 0.787, 0.715 - cos * 0.715 + sin * 0.715, 0.072 + cos * 0.928 + sin * 0.072),
    )


def turn_rgb(rows, red, green, blue):
    """One colour through `rows`, each channel kept within 0-255."""
    return tuple(max(0, min(255, round(r * red + g * green + b * blue))) for r, g, b in rows)


def _turn_argb(rows, argb):
    alpha = (argb >> 24) & 0xFF
    red, green, blue = turn_rgb(rows, (argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF)
    return (alpha << 24) | (red << 16) | (green << 8) | blue


def _turn(image, degrees):
    rows = matrix(degrees)

    # Palette images change only their palette; the bundled faces and most poses are these.
    if image.format() == QImage.Format.Format_Indexed8:
        turned = QImage(image)
        turned.setColorTable([_turn_argb(rows, colour) for colour in image.colorTable()])
        return turned

    # Others change pixel by pixel, without premultiplied alpha.
    turned = image.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(turned.height()):
        for x in range(turned.width()):
            turned.setPixel(x, y, _turn_argb(rows, turned.pixel(x, y)))
    return turned
