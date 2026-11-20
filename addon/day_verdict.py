"""Today's streak verdict, the server's way, with reviews not uploaded yet.

The server judges every day. The one thing the add-on works out itself is today, right after
answering cards it has not uploaded: it adds their review time to what the last profile said,
by the rule in AnkiQuest-Server's docs/mobile-api.md ("day verdicts"), pinned by tests/fixtures/day_verdicts.json.

Plain Python, so the tests load it without Anki.
"""

MINUTE_MS = 60_000
_UNKNOWN, _SYNCING, _MET, _PROTECTED, _PENDING = "unknown", "syncing", "met", "protected", "pending"

# The day's words, as the fixture's `label` names them.
STUDIED, SHORT = "studied", "short"

# The reviews the uploader sends (client.PENDING_SQL), with only what the verdict needs.
UNSENT_SQL = "select id, time from revlog where id > ? and ease > 0 and type < 4 order by id"


def _int(value, default=None):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def verdict(server, pending, now_ms):
    """Today's verdict from `server` (the last profile) and `pending`, reviews the collection
    holds as dicts with `id` and `time_ms`; None when there is no profile, its day has ended or it
    lacks today's `starts_at` and `time_ms` (a server older than this add-on).

    The answer has `met`, `streak_state`, `streak`, `reviews`, `time_ms`, `minutes`,
    `streak_minutes` and `unsent` (the reviews counted that the server does not have yet), as in
    the fixture, plus `waiting`: met, but only once the unsent reviews arrive. `streak` and,
    while not met, `streak_state` are None when an unsent review belongs to an earlier day.
    """
    if not isinstance(server, dict):
        return None
    ends = _int(server.get("day_ends_at"))
    if ends is not None and ends and now_ms >= ends:
        return None
    today = server.get("today") if isinstance(server.get("today"), dict) else {}
    starts, time_ms = _int(today.get("starts_at")), _int(today.get("time_ms"))
    if starts is None or time_ms is None:
        return None

    # Reviews after the last uploaded one count toward today once they fall inside it.
    last = _int(server.get("last_review_id"))
    unsent = []
    if last is not None:
        unsent = [r for r in pending or () if (_int(r.get("id"), 0) or 0) > last]
    counted = [
        r for r in unsent
        if starts <= r["id"] and (ends is None or not ends or r["id"] < ends)
    ]
    earlier = any(r["id"] < starts for r in unsent)
    reviews = max(0, _int(today.get("reviews"), 0)) + len(counted)
    time_ms += sum(_int(r.get("time_ms"), 0) or 0 for r in counted)
    needed = max(0, _int(today.get("streak_minutes"), 0))
    was = server.get("streak_state")
    met = was == "studied" or (reviews > 0 and time_ms >= needed * MINUTE_MS)
    streak = max(0, _int(server.get("streak"), 0)) + (1 if met and was != "studied" else 0)
    if met:
        state = "studied"
    else:
        state = None if earlier else was
    return {
        "met": met,
        "streak_state": state,
        "streak": None if earlier else streak,
        "reviews": reviews,
        "time_ms": time_ms,
        "minutes": max(0, time_ms) // MINUTE_MS,
        "streak_minutes": needed,
        "unsent": len(counted),
        "waiting": met and was != "studied",
    }


def label(found):
    """The words for a `verdict`: studied, unknown, short (reviews under the minimum), protected
    or pending. Reviews today outrank a protected streak, which says nothing was studied yet."""
    if found is None:
        return _UNKNOWN
    if found["met"]:
        return STUDIED
    if found["streak_state"] is None:
        return _UNKNOWN
    if found["reviews"] > 0:
        return SHORT
    if found["streak_state"] == _PROTECTED:
        return _PROTECTED
    return _PENDING


def unsent(col, server):
    """The collection's reviews after the server's `last_review_id`, as `verdict` reads them.
    Call where the collection may be read."""
    last = _int((server or {}).get("last_review_id")) if isinstance(server, dict) else None
    if last is None:
        return []
    return [{"id": row[0], "time_ms": row[1] or 0} for row in col.db.all(UNSENT_SQL, last)]


def _for_display(server, found):
    """Keep lifetime facts; replace today's claims with the already computed verdict."""
    if not isinstance(server, dict):
        return None
    view = dict(server)
    if found is None:
        view.update(streak=None, streak_state=None, today={}, quests=[], at_risk=False,
                    streak_warning=None, _day_status=_UNKNOWN)
        return view
    view.update(streak=found["streak"], streak_state=found["streak_state"],
                today=dict(server.get("today") or {}, reviews=found["reviews"], time_ms=found["time_ms"], minutes=found["minutes"]))
    if found["waiting"]:
        status = _SYNCING
    elif found["met"]:
        status = _MET
    elif label(found) == _PROTECTED:
        status = _PROTECTED
    else:
        status = _UNKNOWN if found["streak"] is None else _PENDING
    view["_day_status"] = status
    if found["met"] or found["streak"] is None:
        view.update(at_risk=False, streak_warning=None)
    return view
