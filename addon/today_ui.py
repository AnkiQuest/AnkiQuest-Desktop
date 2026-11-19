"""Qt pieces of the Today features: the Today settings."""

from aqt.qt import QCheckBox, QLabel

from .language import tr


def settings_section(layout, config, *, notify_layout=None):
    """Appends the Today settings and returns a function that reads them back."""
    heading = QLabel(tr("Today"))
    heading.setStyleSheet("font-weight:bold;margin-top:8px")
    layout.addWidget(heading)
    toggles = {}
    for key, text, default in (
        ("deck_status", "Mark decks finished today, and learning due later today", True),
        ("session_summary", "Show a recap when you leave a study session", True),
        ("review_heatmap", "Show the review heatmap under the deck list", True),
        ("goal_celebrations", "Celebrate when today counts for your streak and when you reach your daily goal", True),
        # Kept on this device: synced settings need a row in tests/fixtures/synced_settings.json.
        ("reduce_motion", "Reduce motion", False),
    ):
        toggles[key] = QCheckBox(tr(text))
        toggles[key].setChecked(bool(config.get(key, default)))
        target = notify_layout if key == "goal_celebrations" and notify_layout is not None else layout
        target.addWidget(toggles[key])
    toggles["reduce_motion"].setToolTip(tr("Show a new companion with a short fade instead of the full reveal."))

    def values():
        return {key: box.isChecked() for key, box in toggles.items()}

    return values
