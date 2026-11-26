"""The companion's bundled art as Qt pictures: each companion's own, as the pinned AnkiQuest-Art
release exports it."""

from pathlib import Path

from aqt.qt import QColor, QIcon, QPainter, QPixmap, Qt

from .share import face_path

_ADDON = Path(__file__).resolve().parent


def pose_path(pose):
    """The bundled file of a pose such as `aki_streak`."""
    return str(_ADDON / "art" / (pose + ".png"))


def pixmap(path, size=None):
    """The picture at `path`, scaled to fit `size` pixels if given."""
    picture = QPixmap(path)
    if size is None:
        return picture
    return picture.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


def silhouette(picture):
    """`picture` as a grey shadow of its shape, for a companion not unlocked yet."""
    shadow = QPixmap(picture)
    painter = QPainter(shadow)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(shadow.rect(), QColor(128, 128, 128, 110))
    painter.end()
    return shadow


def icon(companion):
    """`companion`'s face as a window or tray icon; an empty icon for no companion."""
    path = face_path(companion)
    return QIcon(pixmap(path)) if path else QIcon()
