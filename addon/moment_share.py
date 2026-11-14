"""Recipient choices and authenticated moment sends, shared by desktop windows."""

import json
from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote

from . import share, social_data

_FEATURE = "share_moments"
_MAX_NOTE = 140
_MAX_RECENT = 20
_RECENT = "ankiquestRecentShares"


class _Kind(Enum):
    FRIEND = "user"
    GROUP = "group"


class _Choice(Enum):
    NOBODY = "nobody"
    CIRCLE = "circle"


@dataclass(frozen=True)
class _Target:
    _kind: _Kind
    _id: object
    _label: str

    @property
    def _key(self):
        return "%s:%s" % (self._kind.value, self._id)


@dataclass(frozen=True)
class _Picked:
    _targets: tuple


@dataclass(frozen=True)
class _Sent:
    _recipients: int
    _win: int
    _until: object


def _targets(data, me, recent):
    people = [_Target(_Kind.FRIEND, row["user"], row.get("display") or row["user"])
              for row in data.get("friends", [])]
    groups = [_Target(_Kind.GROUP, row["id"], row["name"]) for row in data.get("groups", [])
              if any(person["user"] != me for person in row.get("members", []))]
    rank = {key: index for index, key in enumerate(recent)}
    return tuple(sorted(people + groups, key=lambda row: (
        rank.get(row._key, len(recent)), row._kind is _Kind.GROUP, row._label.lower(), row._key)))


def _toggle(choice, target):
    if target is _Choice.CIRCLE:
        return _Choice.NOBODY if choice is _Choice.CIRCLE else _Choice.CIRCLE
    picked = list(choice._targets) if isinstance(choice, _Picked) else []
    if target in picked:
        picked.remove(target)
    else:
        picked.append(target)
    return _Picked(tuple(picked)) if picked else _Choice.NOBODY


def _audience(choice):
    if choice is _Choice.CIRCLE:
        return "circle"
    if not isinstance(choice, _Picked) or not choice._targets:
        return None
    return {"friends": [row._id for row in choice._targets if row._kind is _Kind.FRIEND],
            "groups": [row._id for row in choice._targets if row._kind is _Kind.GROUP]}


def _note(text):
    # Python slices Unicode code points, so an astral character is never split.
    return " ".join(text.split())[:_MAX_NOTE] or None


def _moment(win):
    at = win.get("conquest")
    if isinstance(at, int) and not isinstance(at, bool) and at > 0:
        return {"conquest": at}
    value = share.win_id(win)
    return {"win": value} if value else None


def _send(api, win, choice, note):
    moment, audience = _moment(win), _audience(choice)
    if moment is None or audience is None:
        raise ValueError("Choose someone to send this moment to.")
    body = {"moment": moment, "to": audience}
    if _note(note):
        body["note"] = _note(note)
    answer = api._request("/api/share/" + api.user, body)
    return _Sent(int(answer["recipients"]), int(answer["win"]), answer.get("undo_until"))


def _retract(api, sent):
    if not isinstance(sent._until, int) or isinstance(sent._until, bool):
        raise ValueError("This send has no Undo receipt.")
    # Old servers ignore this selector; a stale capability cache must not broaden Undo.
    path = "/api/share/%s/%d?until=%d" % (api.user, sent._win, sent._until)
    return int(api._request(path, method="DELETE")["retracted"])


def _scope(api):
    return json.dumps([api.base, api.user], separators=(",", ":"))


def _recent(profile, api):
    return profile.get(_RECENT, {}).get(_scope(api), [])


def _remember(profile, api, choice):
    if not isinstance(choice, _Picked):
        return
    keys = [target._key for target in choice._targets]
    profile.setdefault(_RECENT, {})[_scope(api)] = list(dict.fromkeys(keys + _recent(profile, api)))[:_MAX_RECENT]


def _load(api, win, recent):
    # Old servers and old local notices keep the existing share actions.
    features = api.capabilities() if hasattr(api, "capabilities") else frozenset()
    if _FEATURE not in features or _moment(win) is None:
        return None
    return _targets(social_data._people(api), unquote(api.user), recent)
