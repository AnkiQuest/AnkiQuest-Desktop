"""Explicit deck completions, verified against Anki's daily progress before sharing."""

import time

from .client import offset_west_min
from .deck_completion import DAY_MS, deck_snapshots

_PROMPTS = "ankiquestDeckPrompts"


def _prompts(profile, api):
    return profile.setdefault(_PROMPTS, {}).setdefault(api.base, {}).setdefault(api.user, {})


def _prompt_due(profile, api, summary):
    record, day = summary.get("deck"), summary.get("day")
    saved = _prompts(profile, api)
    return bool(record and day and not saved.get("muted") and saved.get("shown", {}).get(record["id"]) != day)


def _capture(col):
    """Keep the studied deck when review starts; changing the selection cannot replace it."""
    try:
        deck = col.decks.current()
        if deck and not deck.get("dyn"):
            return {"id": str(deck["id"]), "path": deck["name"]}
    except (AttributeError, KeyError, TypeError):
        pass
    return None


def _finished(col, record, finished_at):
    """Run on the collection worker. Later-today learning also prevents completion."""
    now = int(time.time() * 1000)
    cutoff = col.sched.day_cutoff * 1000
    if not cutoff - DAY_MS <= finished_at <= now < cutoff:
        return None
    rows = deck_snapshots(col, now, offset_west_min(), col.get_config("rollover", 4), only={record["id"]})
    complete = any(row["remaining"] == 0 and row["reviewed_today"] > 0 for row in rows)
    return dict(record) if complete else None


def _automatic(settings, record):
    return any(str(row.get("id")) == record["id"] and row.get("enabled") and row.get("recipients")
               for row in settings.get("decks", []))
