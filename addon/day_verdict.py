"""Today's streak verdict, the server's way, with reviews not uploaded yet.

The server judges every day. The one thing the add-on works out itself is today, right after
answering cards it has not uploaded: it adds their review time to what the last profile said.
The rule is AnkiQuest-Server's crates/rules (today_verdict), called through the shared rules
library (native_rules.py), pinned by tests/fixtures/day_verdicts.json. This module reads the
profile into the library's types and the answer back into the dicts the add-on uses.
"""

from . import native_rules

MINUTE_MS = 60_000
_UNKNOWN, _SYNCING, _MET, _PROTECTED, _PENDING = "unknown", "syncing", "met", "protected", "pending"

# Today counts on observed answers (AnkiQuest Lite) whose review time is not known, short of
# the minimum: the server's `streak_state` and the fixture's label, and a displayed day status.
UNVERIFIED = "unverified"

# The day's words, as the fixture's `label` names them.
STUDIED, SHORT = "studied", "short"

# The server's `streak_state` names, which the library's StreakState spells in capitals.
_STATES = ("studied", UNVERIFIED, _PENDING, _PROTECTED)

# A bound the profile leaves out: no end to today, or no review uploaded yet.
_NO_BOUND = 2 ** 63 - 1

# The reviews the uploader sends (client.PENDING_SQL), with only what the verdict needs.
UNSENT_SQL = "select id, time from revlog where id > ? and ease > 0 and type < 4 order by id"


def _int(value, default=None):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _count(value):
    """A count the library takes: a whole number from 0."""
    return max(0, _int(value, 0))


def _server(rules, server):
    """The profile as the library's ServerDay, or None when it lacks what the rule needs: today's
    `starts_at` and `time_ms` (a server older than this add-on), or names a `streak_state` the
    rule does not know. A profile without `streak_state` has counted nothing today: pending."""
    today = server.get("today") if isinstance(server.get("today"), dict) else {}
    starts, time_ms = _int(today.get("starts_at")), _int(today.get("time_ms"))
    state = server.get("streak_state") or _PENDING
    if starts is None or time_ms is None or state not in _STATES:
        return None
    ends = _int(server.get("day_ends_at"))
    last = _int(server.get("last_review_id"))
    return rules.ServerDay(
        streak=_count(server.get("streak")),
        streak_state=rules.StreakState[state.upper()],
        day_ends_at=ends if ends else _NO_BOUND,
        last_review_id=_NO_BOUND if last is None else last,
        today=rules.ServerToday(
            starts_at=starts,
            reviews=_count(today.get("reviews")),
            observed=_count(today.get("observed")),
            time_ms=time_ms,
            minutes=_count(today.get("minutes")),
            streak_minutes=_count(today.get("streak_minutes")),
        ),
    )


def _name(value):
    """A library enum as the server and fixture name it, or None."""
    return None if value is None else value.name.lower()


def verdict(server, pending, now_ms):
    """Today's verdict from `server` (the last profile) and `pending`, reviews the collection
    holds as dicts with `id` and `time_ms`; None when there is no profile, its day has ended, it
    lacks today's `starts_at` and `time_ms` (a server older than this add-on), names an unknown
    streak state, or the rules library cannot be loaded.

    A pending review without `time_ms` is an observed answer (AnkiQuest Lite); the add-on's own
    reviews always have one.

    The answer has `met`, `streak_state`, `streak`, `reviews`, `observed`, `time_ms`, `minutes`,
    `streak_minutes`, `unsent` (the reviews counted that the server does not have yet) and
    `label`, as in the fixture, plus `waiting`: met, but in that state only once the unsent
    reviews arrive. `streak` and, while not met, `streak_state` are None when an unsent review
    belongs to an earlier day.
    """
    if not isinstance(server, dict):
        return None
    rules = native_rules.load()
    if rules is None:
        return None
    day = _server(rules, server)
    if day is None:
        return None

    # Observed answers have no time_ms; the add-on's own reviews always do.
    reviews = [
        rules.PendingReview(id=_int(r.get("id"), 0) or 0, time_ms=_int(r.get("time_ms"), 0) if "time_ms" in r else None)
        for r in pending or ()
    ]
    found = rules.today_verdict(day, reviews, now_ms)
    if found.is_ended():
        return None
    today = found.verdict
    state = _name(today.streak_state)
    return {
        "met": today.met,
        "streak_state": state,
        "streak": today.streak,
        "reviews": today.reviews,
        "observed": today.observed,
        "time_ms": today.time_ms,
        "minutes": today.minutes,
        "streak_minutes": today.streak_minutes,
        "unsent": today.unsent,
        "label": _name(today.label),
        "waiting": today.met and state != (server.get("streak_state") or _PENDING),
    }


def label(found):
    """The words for a `verdict`: studied, unverified (counted on observed answers short of the
    minimum), unknown, short (reviews under the minimum), protected or pending."""
    if found is None:
        return _UNKNOWN
    return found.get("label", _UNKNOWN)


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
                today=dict(server.get("today") or {}, reviews=found["reviews"], observed=found["observed"],
                               time_ms=found["time_ms"], minutes=found["minutes"]))
    if found["waiting"]:
        status = _SYNCING
    elif found["met"] and found["streak_state"] == UNVERIFIED:
        status = UNVERIFIED
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
