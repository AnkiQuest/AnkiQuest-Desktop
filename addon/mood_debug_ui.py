"""The hidden debug menu for today's mood and pose: a modifier-click on the settings' version
label opens it (as the phone's debug screen hides behind Settings). Saves only to this add-on's
config through its `on_save`; nothing here reaches the server (mood_debug)."""

from aqt.qt import (
    QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, Qt,
)

from . import mood_debug
from .language import tr


class VersionLabel(QLabel):
    """The settings' version label; control-click opens the mood debug menu, plain clicks do
    nothing (the label names a version, not a link)."""

    def __init__(self, text, on_debug=None):
        super().__init__(text)
        self._on_debug = on_debug

    def mousePressEvent(self, event):
        if self._on_debug is not None and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._on_debug()
        super().mousePressEvent(event)


def dialog(parent, config, on_save):
    """The mood and pose override (`mood_debug`) and its thresholds, saved through `on_save`
    into this add-on's config only. None when cancelled; the marker line follows the state."""
    kind, value = mood_debug.Override.read(config)
    window = QDialog(parent)
    window.setWindowTitle(tr("Today's companion (debug)"))
    layout = QVBoxLayout(window)
    limits = mood_debug.thresholds(config)
    override = QComboBox()
    override.setObjectName("ankiquest_debug_override")
    override.addItem(tr("Follow today's streak"), "")
    for mood in mood_debug.Moods:
        override.addItem(mood, mood_debug.stored(mood_debug.Override.MOOD, mood))
    for pose in mood_debug.Poses:
        override.addItem(pose, mood_debug.stored(mood_debug.Override.POSE, pose))
    override.setCurrentIndex(max(0, override.findData(mood_debug.stored(kind, value))))
    row = QHBoxLayout()
    row.addWidget(QLabel(tr("Shown mood and pose:")))
    row.addWidget(override, 1)
    layout.addLayout(row)

    group = QGroupBox(tr("Mood thresholds"))
    group.setLayout(QVBoxLayout())
    fields = {}
    for name, label in (
        ("hopeful_reviews", "Reviews for hopeful (1 or more)"),
        ("frozen_2_days", "Frozen days for frozen 2 (2 or more)"),
        ("frozen_3_days", "Frozen days for frozen 3 (more than frozen 2)"),
        ("hot_days", "Streak days for hot (2 or more)"),
        ("blazing_days", "Streak days for blazing (more than hot)"),
        ("legend_days", "Streak days for legend (more than blazing)"),
        ("freeze_window_minutes", "Minutes before a freeze (1 or more)"),
        ("neglected_days", "Days away for neglected (1 or more)"),
        ("abandoned_days", "Days away for abandoned (more than neglected)"),
        ("dead_days", "Days away for dead (more than abandoned)"),
    ):
        field = QLineEdit(str(limits[name]))
        field.setObjectName("ankiquest_debug_" + name)
        fields[name] = field
        line = QHBoxLayout()
        line.addWidget(QLabel(tr(label)))
        line.addWidget(field, 1)
        group.layout().addLayout(line)
    layout.addWidget(group)

    note = QLabel(tr("Never sent to the server."))
    note.setWordWrap(True)
    layout.addWidget(note)

    error = QLabel(tr("Not saved: each threshold must be in range and above the one before it."))
    error.setObjectName("ankiquest_debug_limits_error")
    error.setWordWrap(True)
    error.hide()
    layout.addWidget(error)

    def wanted_limits():
        stored = {name: field.text().strip() for name, field in fields.items()}
        limits = {}
        for name, text in stored.items():
            limits[name] = int(text) if text.isdigit() else mood_debug.DEFAULT_THRESHOLDS[name]
        return limits

    def accept_or_complain():
        if mood_debug.ordered(wanted_limits()):
            window.accept()
        else:
            error.show()

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = QPushButton(tr("Cancel"))
    cancel.clicked.connect(window.reject)
    save = QPushButton(tr("Save"))
    save.setDefault(True)
    save.clicked.connect(accept_or_complain)
    buttons.addWidget(cancel)
    buttons.addWidget(save)
    layout.addLayout(buttons)

    if not window.exec():
        return None
    limits = wanted_limits()
    if not mood_debug.ordered(limits):
        return None
    return {"debug_override": override.currentData(), "debug_thresholds": mood_debug.thresholds_stored(limits)}
