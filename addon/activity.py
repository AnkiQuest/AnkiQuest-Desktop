"""Activity pages keep server counts and cursors."""
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Optional
from urllib.parse import urlencode


class _Category(Enum):
    ALL = ""
    NEEDS_ACTION = "needs_action"
    MESSAGES = "messages"
    CHALLENGES = "challenges"
    DECK_COMPLETIONS = "deck_completions"
    STUDY_UPDATES = "study_updates"


class _Read(Enum):
    ALL = auto()
    UNREAD = auto()


@dataclass
class _Page:
    items: list
    attention: list
    unread: int
    actions: int
    latest: Optional[int]
    before: Optional[int]
    # Why the server left other players' study out ("upload_first"), or None.
    locked: Optional[str] = None


def _parse(answer):
    if not isinstance(answer, dict) or not isinstance(answer.get("items"), list):
        raise ValueError("Invalid activity response")
    return _Page(answer["items"], answer.get("attention") or [], int(answer.get("unread_count", 0)),
                 int(answer.get("action_count", 0)), answer.get("latest_id"), answer.get("next_before"),
                 locked=answer.get("locked"))


def _load(api, category=_Category.ALL, read=_Read.ALL, before=None):
    query = {"limit": 50}
    if category is not _Category.ALL:
        query["category"] = category.value
    if read is _Read.UNREAD:
        query["unread_only"] = "true"
    if before is not None:
        query["before"] = before
    return _parse(api._request("/api/activity/%s?%s" % (api.user, urlencode(query))))


def _append(previous, page):
    # A refreshed row replaces its old copy; pagination never duplicates a notification.
    rows = {row["id"]: row for row in previous.items}
    rows.update({row["id"]: row for row in page.items})
    return replace(page, items=sorted(rows.values(), key=lambda row: row["id"], reverse=True))
