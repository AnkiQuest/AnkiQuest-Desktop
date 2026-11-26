"""The optimize reminder over the deck list, once per profile open, and its settings switch."""

from enum import Enum, auto

from aqt.qt import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, Qt

from . import optimize_reminder as rule
from .language import tr


class Choice(Enum):
    """What the player did with the reminder."""
    OPEN = auto()
    SNOOZE = auto()
    DISMISS = auto()
    # The window closed another way: nothing changes.
    CLOSED = auto()


def _plain(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def ask(parent, remind):
    """Shows the reminder until the player closes it. Buttons in Android's order: Remind me in a
    week on the left, then Dismiss and Open deck options."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("AnkiQuest")
    layout = QVBoxLayout(dialog)
    title = _plain(tr(rule.TITLE))
    font = title.font()
    font.setBold(True)
    title.setFont(font)
    layout.addWidget(title)
    layout.addWidget(_plain(rule.message(remind, tr)))

    chosen = [Choice.CLOSED]

    def pick(choice):
        chosen[0] = choice
        dialog.accept()

    row = QHBoxLayout()
    buttons = {}
    for choice, text in ((Choice.SNOOZE, rule.SNOOZE), (Choice.DISMISS, rule.DISMISS), (Choice.OPEN, rule.OPEN)):
        button = QPushButton(tr(text))
        button.setObjectName("ankiquest_optimize_" + choice.name.lower())
        button.clicked.connect(lambda _=False, picked=choice: pick(picked))
        buttons[choice] = button
    row.addWidget(buttons[Choice.SNOOZE])
    row.addStretch(1)
    row.addWidget(buttons[Choice.DISMISS])
    row.addWidget(buttons[Choice.OPEN])
    buttons[Choice.OPEN].setDefault(True)
    layout.addLayout(row)
    dialog.exec()
    return chosen[0]


def offer(mw, config, save_config):
    """Reminds the player when the rule says so; `config` and `save_config` are the add-on's."""
    state = rule.decode(config.get(rule.CONFIG_KEY))
    col = getattr(mw, "col", None)
    if isinstance(state, rule.Off) or col is None:
        return
    try:
        found = rule.inputs(col)
    except Exception as error:
        print("ankiquest optimize reminder:", error)
        return
    remind = rule.verdict(found, state)
    if not isinstance(remind, rule.Remind):
        return

    choice = ask(mw, remind)
    if choice is Choice.OPEN:
        from aqt import deckoptions
        deckoptions.display_options_for_deck_id(found.deck)
        return
    event = {Choice.SNOOZE: rule.Event.SNOOZE, Choice.DISMISS: rule.Event.DISMISS}.get(choice)
    if event is None:
        return
    after = rule.next_state(state, event, found.today, found.last_optimized_day)
    save_config({rule.CONFIG_KEY: rule.encode(after)})


def settings_switch(layout, config):
    """Appends the switch and returns a function that reads it back as the config value. Turning
    it on keeps a snooze or dismissal."""
    box = QCheckBox(tr(rule.SETTING))
    box.setObjectName("ankiquest_optimize_reminder")
    box.setToolTip(tr(rule.SETTING_SUMMARY))
    state = rule.decode(config.get(rule.CONFIG_KEY))
    box.setChecked(not isinstance(state, rule.Off))
    layout.addWidget(box)
    note = _plain(tr(rule.SETTING_SUMMARY))
    layout.addWidget(note)

    def values():
        event = rule.Event.TURN_ON if box.isChecked() else rule.Event.TURN_OFF
        return {rule.CONFIG_KEY: rule.encode(rule.next_state(state, event, None, None))}

    return values
