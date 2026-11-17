"""Share a win with friends, or export its server picture with a private local fallback."""

from pathlib import Path

from aqt.qt import (
    QApplication,
    QFileDialog,
    QFont,
    QHBoxLayout,
    QImage,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
)

from . import companion_art, share
from .inbox import error_text
from .language import tr

state = {"popup": None}


def _font(pixels, bold):
    font = QFont()
    font.setPixelSize(pixels)
    font.setBold(bold)
    return font


def picture(png):
    """The PNG bytes as a QImage; None when Qt cannot read them."""
    image = QImage()
    return image if image.loadFromData(png, "PNG") else None


def copy_card(found):
    """Puts the card on the clipboard. Nothing is published."""
    image = picture(found["png"])
    if image is None:
        return tr("Could not read the picture.")
    QApplication.clipboard().setImage(image)
    return tr("The picture is on the clipboard.")


def save_card(path, found):
    """Writes the card to `path`. Nothing is published."""
    try:
        Path(path).write_bytes(found["png"])
    except OSError:
        return tr("Could not save the picture.")
    return tr("Picture saved.")


def copy_link(linked):
    """Puts the public link, in the server's invitation, on the clipboard."""
    QApplication.clipboard().setText(linked["text"] or linked["url"])
    return tr("A public link is on the clipboard. Anyone with it can see this card.")


def ask_path(parent):
    path, _ = QFileDialog.getSaveFileName(parent, tr("Save image…"), "ankiquest-win.png", "PNG (*.png)")
    if path and not path.lower().endswith(".png"):
        path += ".png"
    return path or None


def copy_text(win, server):
    QApplication.clipboard().setText(share.invitation(win, server, tr))
    return tr("An invitation is on the clipboard.")


def same_account(api, current):
    return [api.base, api.user, api.token] == [current.base, current.user, current.token]


class Superseded(Exception):
    """Queued work did not start: the account or profile it was for is no longer open."""


def run_owned(background, owns, work, done, **options):
    """Runs `work` with `background` only while `owns()`: when queued, when it starts and when
    its reply arrives. Signing out or switching profile cancels writes that have not started."""
    if not owns():
        return

    def guarded():
        if not owns():
            raise Superseded()
        return work()

    def arrived(future):
        if owns():
            done(future)

    background(guarded, arrived, **options)


def _plain(text, bold=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if bold:
        label.setFont(_font(15, True))
    return label


def _head(win, companion):
    head = QHBoxLayout()
    asset = share.face_path(companion)
    if asset:
        image = QLabel()
        image.setPixmap(companion_art.pixmap(asset, companion, 56))
        head.addWidget(image)
    words = QVBoxLayout()
    words.addWidget(_plain(win["title"], True))
    words.addWidget(_plain(win["body"]))
    head.addLayout(words, 1)
    return head


class Sharing:
    """Fetch a server picture or draw it locally; reuse it only for its account and profile."""

    def __init__(self, dialog, api, win, current_client, run, status, companion=None):
        self.dialog, self.api, self.win = dialog, api, win
        self.current_client, self.run, self.status = current_client, run, status
        self._companion = companion
        self.found = None
        self.waiting = []

    def owned(self):
        if same_account(self.api, self.current_client()):
            return True
        self.status.setText(tr("This win belongs to an AnkiQuest account that is no longer signed in."))
        return False

    def to_friends(self, button):
        if not self.owned():
            return
        button.setEnabled(False)
        self.status.setText(tr("Sharing…"))

        def sent(future):
            try:
                recipients = future.result()
            except Exception as error:
                button.setEnabled(True)
                self.status.setText(tr("Couldn't share it (%s).") % error_text(error))
                return
            self.status.setText(share.sent_text(recipients, tr))

        self.run(lambda: share.send(self.api, self.win), sent)

    def with_card(self, then):
        """Runs `then(found)` once the card is here, fetching it first if needed."""
        if not self.owned():
            return
        self.waiting.append(then)
        if len(self.waiting) > 1:
            return
        self.status.setText(tr("Getting the picture…"))

        # Cached pictures still pass through the account/profile-bound runner.
        def fetch():
            if self.found is not None:
                return self.found
            # Streak exports use the same heat design online and offline.
            if self.win.get("picture_streak") is not None:
                return None
            return share.card(self.api, self.win) if share.has_card(self.win) else None

        self.run(fetch, self.fetched)

    def fetched(self, future):
        waiting, self.waiting = self.waiting, []
        if not self.owned():
            return
        try:
            self.found = future.result()
        except Exception:
            self.found = None
        if self.found is None or picture(self.found["png"]) is None:
            # Qt's bundled art is read on this UI callback, after ownership is checked.
            from . import share_picture
            try:
                palette = self.dialog.palette() if self.dialog is not None else QApplication.palette()
                self.found = share_picture.render(self.win, self._companion, palette)
            except Exception as error:
                self.status.setText(tr("Could not get the picture (%s).") % error_text(error))
                return
        for action in waiting:
            action(self.found)

    def to_clipboard(self):
        self.with_card(lambda found: self.status.setText(copy_card(found)))

    def to_file(self):
        path = ask_path(self.dialog)
        if path:
            self.with_card(lambda found: self.status.setText(save_card(path, found)))

    def to_link(self, button):
        """Makes the win's public page, only because the player asked for a link."""
        if not self.owned():
            return
        button.setEnabled(False)
        self.status.setText(tr("Making a public link…"))

        def linked(future):
            button.setEnabled(True)
            try:
                found = future.result()
            except Exception as error:
                self.status.setText(tr("Couldn't make a link (%s).") % error_text(error))
                return
            self.status.setText(copy_link(found))

        self.run(lambda: share.link(self.api, self.win), linked)

    def to_text(self):
        self.status.setText(copy_text(self.win, self.api.base))


def _buttons(sharing):
    friends = QPushButton(tr("Share with friends"))
    friends.clicked.connect(lambda: _route(sharing, lambda: sharing.to_friends(friends)))
    copy = QPushButton(tr("Copy as image"))
    save = QPushButton(tr("Save image…"))
    text = QPushButton(tr("Copy text"))
    text.clicked.connect(sharing.to_text)
    copy.clicked.connect(sharing.to_clipboard)
    save.clicked.connect(sharing.to_file)
    if not share.has_card(sharing.win):
        return [friends, copy, save, text]
    public = QPushButton(tr("Copy public link"))
    public.setToolTip(tr("Makes a public page for this card. Anyone with the link can see it."))
    public.clicked.connect(lambda: sharing.to_link(public))
    return [friends, copy, save, text, public]


def _route(sharing, legacy):
    """Existing entry points open the recipient picker only on supporting servers."""
    from . import moment_share
    if not sharing.owned():
        return
    if moment_share._moment(sharing.win) is None or not hasattr(sharing.api, "capabilities"):
        legacy()
        return

    def checked(future):
        if not sharing.owned():
            return
        # Unknown features: send the old way, as to a server without the recipient picker.
        try:
            features = future.result()
        except Exception:
            legacy()
            return
        if not moment_share._supported(sharing.win, features):
            legacy()
            return
        win_dialog(sharing.dialog, sharing.api, sharing.win, sharing._companion, sharing.current_client, sharing.run).show()

    sharing.run(sharing.api.capabilities, checked)


def win_dialog(parent, api, win, companion, current_client, run, on_sent=None):
    from . import moment_share_ui
    return moment_share_ui._dialog(parent, api, win, companion, current_client, run, on_sent)


def _corner(dialog, parent):
    """Bottom right of Anki's window, out of the way of the card being studied."""
    if parent is None:
        return
    frame = parent.frameGeometry()
    size = dialog.sizeHint()
    dialog.move(frame.right() - size.width() - 40, frame.bottom() - size.height() - 60)


def offer(parent, api, win, companion, current_client, run):
    """Shows a just-announced win without taking focus; a newer win replaces the one showing."""
    previous = state["popup"]
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass
    dialog = win_dialog(parent, api, win, companion, current_client, run)
    dialog.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    dialog.finished.connect(lambda *_: state.update(popup=None) if state["popup"] is dialog else None)
    state["popup"] = dialog
    _corner(dialog, parent)
    dialog.show()
    return dialog


def share_toggle(sharing, buttons):
    """A checkable "Share" button and a hidden column of `buttons` that it shows and hides.
    On servers with the recipient picker, the button opens the picker instead."""
    column = QWidget()
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    for button in buttons:
        layout.addWidget(button)
    column.hide()
    toggle = QPushButton(tr("Share"))
    toggle.setCheckable(True)
    toggle.toggled.connect(lambda checked: _route(sharing, lambda: column.setVisible(checked)))
    return toggle, column
