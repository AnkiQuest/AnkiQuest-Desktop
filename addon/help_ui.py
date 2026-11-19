"""The Tools menu's help entries, in Android's About order: Rate AnkiQuest, AnkiQuest changelog
and Report a bug, and the changelog dialog. Anki's own Help menu covers Anki."""

from pathlib import Path

from aqt.qt import (
    QAction,
    QApplication,
    QDesktopServices,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    Qt,
    QTextBrowser,
    QUrl,
    QVBoxLayout,
)
from aqt.utils import tooltip

from . import links, release_notes, updates
from .language import tr

ADDON_DIR = Path(__file__).parent


def open_link(url):
    """Opens `url` in the browser. When nothing opens it, copies it so the player can paste it."""
    from anki.utils import no_bundled_libs

    # Anki's openLink does the same, but does not say whether a browser took the link.
    with no_bundled_libs():
        opened = QDesktopServices.openUrl(QUrl(url))
    if opened:
        return
    QApplication.clipboard().setText(url)
    tooltip(tr("No app can open the link. Link copied."))


def installed_label(addon_dir):
    """The installed version as Settings and the changelog show it."""
    installed = updates.installed(addon_dir)
    if installed is None:
        return tr("Local copy")
    return updates.label(installed)


def setup(mw, menu):
    """Adds the help entries to the end of `menu`."""
    menu.addSeparator()
    rate = rate_menu(mw)
    menu.addAction(rate.menuAction())

    # The changelog opens in Anki, from the notes packaged with this version.
    changes = QAction(tr("AnkiQuest changelog"), mw)
    changes.triggered.connect(lambda: changelog(mw, ADDON_DIR))
    menu.addAction(changes)

    _add(mw, menu, tr("Report a bug"), links.BUG_FORM)
    return rate


def rate_menu(parent):
    """Rate AnkiQuest's two places: AnkiWeb for its installs, GitHub for the rest. Offered only
    in the Tools menu (the add-on's About) and the changelog, as on Android."""
    rate = QMenu(tr("Rate AnkiQuest"), parent)
    for target in links.RateTarget:
        _add(parent, rate, tr(target.title), target.url)
    return rate


def changelog(parent, addon_dir):
    """Opens the AnkiQuest changelog: this version's release notes, All releases and Rate AnkiQuest,
    as on Android's changelog screen."""
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle(tr("AnkiQuest changelog"))
    dialog.resize(560, 520)
    layout = QVBoxLayout(dialog)

    # The release this is, and its notes; links in them open in the browser.
    release = QLabel(installed_label(addon_dir))
    release.setObjectName("ankiquest_changelog_release")
    font = release.font()
    font.setBold(True)
    release.setFont(font)
    layout.addWidget(release)
    notes = QTextBrowser()
    notes.setOpenLinks(False)
    notes.anchorClicked.connect(lambda url: open_link(url.toString()))
    notes.setHtml(release_notes.html(release_notes.read()))
    layout.addWidget(notes)

    # Android's buttons, in its order, at the end of the row.
    buttons = QHBoxLayout()
    buttons.addStretch()
    releases = QPushButton(tr("All releases"))
    releases.setObjectName("ankiquest_changelog_releases")
    releases.setAutoDefault(False)
    releases.clicked.connect(lambda: open_link(links.RELEASES))
    buttons.addWidget(releases)
    rate = QPushButton(tr("Rate AnkiQuest"))
    rate.setObjectName("ankiquest_changelog_rate")
    rate.setAutoDefault(False)
    rate.setMenu(rate_menu(rate))
    buttons.addWidget(rate)
    layout.addLayout(buttons)

    dialog.open()
    return dialog


def _add(parent, menu, title, url):
    action = QAction(title, parent)
    action.triggered.connect(lambda: open_link(url))
    menu.addAction(action)
    return action
