"""The Tools menu's help entries, in Android's About order: Rate AnkiQuest, AnkiQuest changelog
and Report a bug. Anki's own Help menu covers Anki."""

from aqt.qt import QAction, QApplication, QDesktopServices, QMenu, QUrl
from aqt.utils import tooltip

from . import links
from .language import tr


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


def setup(mw, menu):
    """Adds the help entries to the end of `menu`."""
    menu.addSeparator()

    # Two places to rate: AnkiWeb for its installs, GitHub for the rest.
    rate = QMenu(tr("Rate AnkiQuest"), mw)
    for target in links.RateTarget:
        _add(mw, rate, tr(target.title), target.url)
    menu.addAction(rate.menuAction())

    _add(mw, menu, tr("AnkiQuest changelog"), links.RELEASES)
    _add(mw, menu, tr("Report a bug"), links.BUG_FORM)
    return rate


def _add(mw, menu, title, url):
    action = QAction(title, mw)
    action.triggered.connect(lambda: open_link(url))
    menu.addAction(action)
    return action
