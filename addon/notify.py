"""What the desktop says out loud. The server writes the words; this decides when."""

import html

FRESH_SECONDS = 86_400
HOUR_MS = 3_600_000


def rich(text):
    """Server words for a rich-text tooltip: never markup, line breaks kept."""
    return html.escape(str(text)).replace("\n", "<br>")


def feedback(response, show_feedback):
    """The upload banner: headlines always, the plain XP line only while reviewing."""
    told = response.get("feedback") or {}
    headlines = list(told.get("headlines") or [])
    status = told.get("status")
    if headlines:
        return "<br>".join(rich(line) for line in headlines + ([status] if status else [])), True
    if status and show_feedback:
        return rich(status), False
    return None


def notice(entry):
    """A server notification as tooltip text, with its title and body escaped."""
    title, body = rich(entry.get("title", "")), rich(entry.get("body", ""))
    return "%s<br>%s" % (title, body) if body else title


def streak_warning(profile, hours, now_ms, warned_for):
    """Once per Anki day, within the configured hours before it ends."""
    warning = profile.get("streak_warning")
    ends_at = profile.get("day_ends_at")
    if hours <= 0 or not warning or not ends_at or warned_for == ends_at:
        return None
    if not 0 < ends_at - now_ms <= hours * HOUR_MS:
        return None
    return notice(warning), ends_at


def fresh_messages(inbox, cursor, now_s):
    """Collect missed arrivals once, including those received while Anki was closed."""
    fresh = []
    for entry in sorted(inbox, key=lambda entry: entry["id"]):
        if entry["id"] <= cursor:
            continue
        cursor = entry["id"]
        if entry.get("quiet"):
            continue
        fresh.append(entry)
    return fresh, cursor
