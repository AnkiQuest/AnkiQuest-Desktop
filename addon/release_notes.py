"""The release notes bundled with this add-on version. The release workflow (addon.yml) publishes
the same file as the notes of each addon-<n> release, so the add-on shows the notes of the release
it was built from. Rendered as Android's AnkiquestReleaseNotes does."""

from pathlib import Path
import re

FILE = Path(__file__).with_name("release-notes.md")

PARAGRAPH = re.compile(r"\n\s*\n")
LINK = re.compile(r"\[([^\]]+)]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def read():
    return FILE.read_text("utf-8")


def html(markdown):
    """`markdown` as rich text: paragraphs, bold text and links. Other syntax stays as written."""
    paragraphs = (part.strip() for part in PARAGRAPH.split(markdown))
    return "".join("<p>%s</p>" % _inline(part) for part in paragraphs if part)


def _inline(text):
    text = LINK.sub(r'<a href="\2">\1</a>', _escape(text))
    return BOLD.sub(r"<b>\1</b>", text)


def _escape(text):
    # Android escapes these four; html.escape would also change apostrophes.
    for raw, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;")):
        text = text.replace(raw, entity)
    return text
