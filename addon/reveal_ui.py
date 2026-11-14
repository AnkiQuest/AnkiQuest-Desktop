"""The window that plays companion_reveal's reveal when a companion joins."""

import math

from aqt.qt import (
    QColor,
    QDialog,
    QElapsedTimer,
    QHBoxLayout,
    QLinearGradient,
    QPainter,
    QPointF,
    QPushButton,
    QRadialGradient,
    QRectF,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)

from . import companion_art, companion_reveal, moments, moods, share_ui
from .companion_reveal import Motion, Phase
from .language import tr

STAGE_WIDTH, STAGE_HEIGHT = 360, 320
ART_PX = 180
FRAME_MS = 16
PARTICLES = 24
BACKGROUND = QColor(20, 18, 31)

# The falling card's size.
CARD_WIDTH, CARD_HEIGHT = 56, 80


# The add-on's own setting, off by default. Anki's Reduce motion is on by default, so it would
# hide the reveal from most players.
REDUCE_MOTION = "reduce_motion"


def motion(config):
    """Reduced when the player turned on Reduce motion in the AnkiQuest settings."""
    return Motion.REDUCED if config.get(REDUCE_MOTION) is True else Motion.FULL


def _eased(t):
    return 1 - (1 - t) ** 2


def _colour(rgb, alpha):
    return QColor(rgb[0], rgb[1], rgb[2], max(0, min(255, int(alpha))))


class _Stage(QWidget):
    """Where the reveal is drawn; a click skips to the companion."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        self.setFixedSize(STAGE_WIDTH, STAGE_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._window._paint(painter)
        painter.end()

    def mousePressEvent(self, _event):
        self._window._skip()


class RevealWindow:
    """The reveal of the companion that `item`, an unlock moment, names.

    `chosen` is the player's companion; "Choose" shows only for another one and calls
    `on_choose(companion)`. `sharing(dialog, run, status)` gives the moment's share_ui.Sharing,
    or None when it cannot be shared. `run(work, done)` runs work in the background."""

    def __init__(self, parent, item, how, chosen, on_choose, sharing, run):
        self.companion = moments.joined(item)
        self.reveal = companion_reveal.Reveal(how)
        self._colours = companion_reveal.COLOURS[companion_reveal.beam(self.companion)]
        self._run_task = run
        self._elapsed = 0
        art = companion_art.pose_path(moments._pose(item, self.companion))
        self._art = companion_art.pixmap(art, self.companion, ART_PX)

        dialog = self.dialog = QDialog(parent)
        dialog.setWindowTitle(item["title"])
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(self._closed)
        layout = QVBoxLayout(dialog)
        self.stage = _Stage(self)
        layout.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignHCenter)

        # The name, the condition met and the buttons wait for the companion.
        self.details = QWidget()
        lines = QVBoxLayout(self.details)
        lines.setContentsMargins(0, 0, 0, 0)
        title, body = share_ui._plain(item["title"], True), share_ui._plain(item["body"])
        status = share_ui._plain("")
        for label in (title, body):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lines.addWidget(label)
        buttons = QHBoxLayout()
        lines.addLayout(buttons)
        self.choose = QPushButton(tr("Choose %s") % moods.NAMES[self.companion])
        self.choose.clicked.connect(lambda: self._chose(on_choose))
        self.choose.setVisible(chosen != self.companion)
        buttons.addWidget(self.choose)

        # Sharing offers what the moment card offers.
        found = sharing(dialog, self._run, status)
        self.share = None
        column = None
        if found is not None:
            friends, *options = share_ui._buttons(found)
            friends.setText(tr("Tell friends"))
            self.share, column = share_ui.share_toggle([friends, *options])
            buttons.addWidget(self.share)
        later = self.later = QPushButton(tr("Later"))
        later.clicked.connect(dialog.reject)
        buttons.addWidget(later)
        if column is not None:
            lines.addWidget(column)
        lines.addWidget(status)
        layout.addWidget(self.details)

        self._clock = QElapsedTimer()
        self._timer = QTimer(dialog)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._shown()

    def start(self):
        self.dialog.show()
        self._clock.start()
        if self.reveal.duration_ms() is not None:
            self._timer.start()

    def _run(self, work, done):
        def arrived(future):
            if self.reveal.phase != Phase.CLOSED:
                done(future)

        self._run_task(work, arrived)

    def _tick(self):
        self.run_for(self._clock.restart())

    def run_for(self, ms):
        """Moves the animation on by `ms` milliseconds."""
        self._elapsed += ms
        while self.reveal.duration_ms() is not None and self._elapsed >= self.reveal.duration_ms():
            self._elapsed -= self.reveal.duration_ms()
            self.reveal.advance()
        self._shown()
        self.stage.update()

    def _skip(self):
        self.reveal.skip()
        self._shown()
        self.stage.update()

    def _shown(self):
        """The details and buttons show once the companion does; the clock stops then."""
        waiting = self.reveal.phase == Phase.SHOWN
        self.details.setVisible(waiting)
        if waiting:
            self._timer.stop()
            self.later.setFocus()

    def _chose(self, on_choose):
        on_choose(self.companion)
        self.dialog.accept()

    def _closed(self, _result):
        self._timer.stop()
        self.reveal.close()

    def _progress(self):
        duration = self.reveal.duration_ms()
        return 1.0 if duration is None else min(1.0, self._elapsed / duration)

    def _paint(self, painter):
        painter.fillRect(self.stage.rect(), BACKGROUND)
        t = self._progress()
        centre = QPointF(STAGE_WIDTH / 2, STAGE_HEIGHT / 2)
        phase = self.reveal.phase

        # Each phase draws on what the one before left.
        if phase == Phase.FALLING:
            landing = centre.y()
            card = QPointF(centre.x(), -CARD_HEIGHT + (landing + CARD_HEIGHT) * _eased(t))
            if t > 0.7:
                self._glow(painter, centre, 90 * (t - 0.7) / 0.3, 200)
            self._card(painter, card)
        elif phase == Phase.BEAM:
            self._beam(painter, 30 + 90 * _eased(t), 200 * min(1.0, t * 2))
            self._glow(painter, centre, 90, 200)
            self._card(painter, centre)
        elif phase == Phase.BURST:
            self._beam(painter, 120, 200 * (1 - t))
            self._particles(painter, centre, t)
            self._companion(painter, centre, t)
        elif phase == Phase.FADING:
            self._companion(painter, centre, t)
        else:
            self._glow(painter, centre, ART_PX * 0.6, 120)
            self._companion(painter, centre, 1.0)

    def _glow(self, painter, centre, radius, alpha):
        if radius <= 0:
            return
        gradient = QRadialGradient(centre, radius)
        gradient.setColorAt(0, _colour(self._colours[0], alpha))
        gradient.setColorAt(1, _colour(self._colours[-1], 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(centre, radius, radius)

    def _card(self, painter, at):
        rect = QRectF(at.x() - CARD_WIDTH / 2, at.y() - CARD_HEIGHT / 2, CARD_WIDTH, CARD_HEIGHT)
        painter.setPen(_colour(self._colours[0], 255))
        painter.setBrush(QColor(250, 248, 255))
        painter.drawRoundedRect(rect, 8, 8)

    def _beam(self, painter, width, alpha):
        """A vertical beam across the stage, brightest in the middle, in the beam's colours."""
        left = (STAGE_WIDTH - width) / 2
        gradient = QLinearGradient(left, 0, left + width, 0)
        gradient.setColorAt(0, _colour(self._colours[0], 0))
        if len(self._colours) == 1:
            gradient.setColorAt(0.5, _colour(self._colours[0], alpha))
        else:
            last = len(self._colours) - 1
            for index, rgb in enumerate(self._colours):
                gradient.setColorAt(0.1 + 0.8 * index / last, _colour(rgb, alpha))
        gradient.setColorAt(1, _colour(self._colours[-1], 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(QRectF(left, 0, width, STAGE_HEIGHT))

    def _particles(self, painter, centre, t):
        painter.setPen(Qt.PenStyle.NoPen)
        distance = 20 + 150 * _eased(t)
        radius = 1.5 + 5 * (1 - t)
        for index in range(PARTICLES):
            angle = 2 * math.pi * index / PARTICLES
            point = QPointF(centre.x() + distance * math.cos(angle), centre.y() + distance * math.sin(angle))
            painter.setBrush(_colour(self._colours[index % len(self._colours)], 255 * (1 - t)))
            painter.drawEllipse(point, radius, radius)

    def _companion(self, painter, centre, opacity):
        painter.setOpacity(opacity)
        painter.drawPixmap(int(centre.x() - self._art.width() / 2), int(centre.y() - self._art.height() / 2), self._art)
        painter.setOpacity(1.0)


def play(parent, item, how, chosen, on_choose, sharing, run):
    """Shows the reveal for `item` and returns its window."""
    window = RevealWindow(parent, item, how, chosen, on_choose, sharing, run)
    window.start()
    return window
