"""Account-scoped moments. Profile records survive restarts and verified address moves."""

from . import inbox, moods, share

_KEY = "ankiquestMoments"
_PRIORITY = {
    "secured": 110, "streak": 100, "level": 90, "rank": 80, "achievement": 70,
    "record": 60, "leech": 55, "conquered": 50, "goal": 40, "quest": 30, "session": 0,
}
_POSES = {
    "level": moods.WINNER,
    "rank": moods.WINNER, "achievement": moods.WINNER, "quest": moods.WINNER,
    "record": moods.CELEBRATE, "conquered": moods.CELEBRATE, "goal": moods.CELEBRATE,
}


def _record(profile, account):
    records = profile.setdefault(_KEY, [])
    for record in records:
        if record["account"] == list(account):
            return record
    record = {"account": list(account), "pending": [], "seen": [], "quiet": []}
    records.append(record)
    return record


def _offer(profile, account, items):
    """Keep every new moment; a later server row can add sharing details to a local one."""
    record = _record(profile, account)
    seen = set(record["seen"])
    if any(item["topic"] == "session" for item in items):
        record["pending"] = [item for item in record["pending"] if item["topic"] != "session"]
    waiting = {item["key"]: item for item in record["pending"]}
    for item in items:
        key = item["key"]
        if key in seen:
            continue
        if key in waiting:
            if item.get("share"):
                waiting[key]["share"] = item["share"]
            continue
        # The daily streak cue is an explicit exception to quiet rows, shared with Android.
        if item.get("quiet") and item["topic"] != "secured":
            record["quiet"].append(key)
            record["seen"].append(key)
            seen.add(key)
            continue
        saved = dict(item)
        record["pending"].append(saved)
        waiting[key] = saved


def _pending(profile, account):
    """The moments to show; an unlock of a companion without art here waits in the queue until
    an update adds it, as on the app."""
    items = [item for item in _record(profile, account)["pending"] if _drawable(item)]
    return sorted(items, key=lambda item: (-_PRIORITY.get(item["topic"], 30), -item["at"], item["key"]))


def _acknowledge(profile, account, keys):
    """Dismissal, not a pause or an account switch, consumes the displayed moments."""
    record = _record(profile, account)
    keys = set(keys)
    record["pending"] = [item for item in record["pending"] if item["key"] not in keys]
    record["seen"].extend(sorted(keys - set(record["seen"])))


def _quiet_count(profile, account):
    return len(_record(profile, account)["quiet"])


def _clear_quiet(profile, account):
    _record(profile, account)["quiet"] = []


def _notice(entry):
    # Cheers and friends' shares may carry our key too; only our own win belongs here.
    if not inbox.shareable(entry):
        return None
    item = {
        "key": entry.get("moment") or "notice:%d" % entry["id"],
        "topic": entry.get("topic") or "unlocks",
        "title": entry.get("title") or "", "body": entry.get("body") or "",
        "at": int(entry.get("created_at") or 0) * 1000,
        "quiet": bool(entry.get("quiet")), "share": share.win_from_entry(entry),
        # The row, and whether another device has read it yet (companion_reveal.due).
        "notice": entry.get("id"), "unread": not entry.get("read_at"),
    }
    return item


def _drawable(item):
    # A card for a companion without art here would show another companion.
    return item["topic"] != "companion" or joined(item) is not None


def _held(item):
    """An unlock nobody has seen yet, offered whatever the inbox cursor: Server#16 sends it
    only once the add-on draws its companion, by then below the cursor. _offer skips the
    ones already shown."""
    return item["topic"] == "companion" and item["unread"] is True


def _rank(change, place, week, at):
    return {
        "key": "rank:%s:%d" % (week or 0, place), "topic": "rank", "at": at,
        "title": change.get("title") or "", "body": change.get("body") or "",
        "share": share.win_from_place(change, place) if place <= 3 else None,
    }


def joined(item):
    """The companion an unlock moment names; None for other moments and unknown companions."""
    if item["topic"] != "companion" or ":" not in item["key"]:
        return None
    found = item["key"].split(":", 1)[1]
    return found if found in moods.NAMES else None


def shown_companion(item, companion):
    """The companion an item's art shows: the one that joined for an unlock, else `companion`."""
    return joined(item) or companion


def _pose(item, companion):
    # A milestone has its own pose; a counted day burns as hot as its streak, as on the phone.
    if item["topic"] == "streak":
        return moods.companion_pose(companion, "aki_streak_milestone")
    if item["topic"] == "secured":
        return moods.companion_pose(companion, moods.streak_pose(moods.FIRE, item.get("streak") or 1))
    return moods.art(companion, _POSES.get(item["topic"], moods.CELEBRATE))


def _conquest(item, translate):
    return {
        "key": "conquered:%d" % item["at"], "topic": "conquered", "at": item["at"],
        "title": translate("Card conquered!"),
        "body": translate("You learned a card that used to be difficult."),
    }
