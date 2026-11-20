import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from ipaddress import ip_address, ip_network

DEFAULT_SERVER = "https://ankiquest.org"

_LOCAL_NETWORKS = tuple(
    ip_network(cidr)
    for cidr in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)

MAX_PENDING = 5000
MAX_DELETES = 100
DELETE_QUERY_SIZE = 500
UNDO_WINDOW_MS = 2 * 86_400_000
REVIEW_FILTER = "where id > ? and ease > 0 and type < 4"
WINDOW_SQL = (
    "select id, cid, lastIvl, ivl, time, type, ease from revlog "
    + REVIEW_FILTER + " order by id"
)
PENDING_SQL = WINDOW_SQL + " limit %d" % MAX_PENDING
COUNT_SQL = "select count(*) from revlog " + REVIEW_FILTER
# Why the server left other players out of an answer: "upload_first" until the player's
# first uploaded review, "sign_in" for nobody signed in. Absent otherwise.
LOCK_HEADER = "X-Ankiquest-Locked"


def offset_west_min():
    offset = datetime.now().astimezone().utcoffset()
    return -int(offset.total_seconds() // 60) if offset else 0


def rows_to_reviews(rows):
    return [
        {"id": r[0], "cid": r[1], "last_ivl": r[2], "ivl": r[3], "time_ms": r[4], "kind": r[5], "ease": r[6]}
        for r in rows
    ]


# The capability of a server that offers two-factor authentication.
TWO_FACTOR = "two_factor"


class SecondFactor(Enum):
    """Where a password sign-in stands with two-factor authentication, as its refusal says."""

    # Not about a second factor: a wrong password, or a server without two-factor.
    NONE = "none"
    # The password is right and the account wants a code; none was sent.
    ASKED = "asked"
    # The code sent is wrong or was used before.
    REFUSED = "refused"
    # Too many wrong codes lately; the server says when to try again.
    LOCKED = "locked"


# The same words as the website and the Android app, in that order of the steps above.
_SECOND_FACTOR_TEXT = {
    SecondFactor.ASKED: "Enter the code from your authenticator app.",
    SecondFactor.REFUSED: "That code is not right.",
    SecondFactor.LOCKED: "Too many wrong codes. Try again in 15 minutes.",
}


class ServerError(Exception):
    """The server answered with an error status. `status` is the HTTP code; `message` is the server's own words, if any.
    `second_factor` is set by `sign_in` when the server asks for a two-factor code."""

    def __init__(self, status, message, asks_code=False):
        super().__init__(message or "HTTP Error %d" % status)
        self.status = status
        self.message = message
        self.asks_code = asks_code
        self.second_factor = SecondFactor.NONE


def second_factor_text(error):
    """The untranslated words for a sign-in held back for its second factor; None for any other refusal."""
    return _SECOND_FACTOR_TEXT.get(error.second_factor)


# Android's aq_server_outdated (AnkiQuest-Android#408). The add-on needs the current
# AnkiQuest-Server; an endpoint or feature it lacks gets this one message instead of a fallback.
OUTDATED = "Update your AnkiQuest server"


class Outdated(Exception):
    """The server lacks an endpoint or feature this add-on needs."""

    def __init__(self):
        super().__init__(OUTDATED)


def outdated(error):
    """Whether `error` means the server is older than this add-on: Outdated, or a 404 from an endpoint."""
    return isinstance(error, Outdated) or getattr(error, "status", None) == HTTPStatus.NOT_FOUND


class InsecureServer(ValueError):
    """The server cannot receive an account password securely."""


def _error_body(error):
    try:
        body = json.load(error)
    except (ValueError, AttributeError):
        return {}
    return body if isinstance(body, dict) else {}


def open_url(url, data=None, headers=None, method=None, timeout=20):
    """Opens `url`, turning an error status into a ServerError that carries the server's `{"error": ...}` text."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        body = _error_body(error)
        raise ServerError(error.code, body.get("error") or "", body.get("second_factor") is True) from None


class Rows(list):
    """A list answer, and why the server left other players out of it (LOCK_HEADER)."""
    locked = None


def _locked(answer, response):
    # A list answer keeps the lock with its rows; an object answer names it itself.
    lock = (getattr(response, "headers", None) or {}).get(LOCK_HEADER)
    if lock is None or not isinstance(answer, list):
        return answer
    rows = Rows(answer)
    rows.locked = lock
    return rows


def request_json(url, body=None, headers=None, timeout=20, method=None):
    """Sends `body` as JSON (a GET when it is None, else a POST unless `method` says otherwise)
    and returns the decoded answer."""
    headers = dict(headers or {}, **{"Content-Type": "application/json"})
    data = None if body is None else json.dumps(body).encode()
    with open_url(url, data, headers, method=method, timeout=timeout) as response:
        if response.status == HTTPStatus.NO_CONTENT:
            return None
        return _locked(json.load(response), response)


def _local_host(host):
    name = host.removesuffix(".")
    if name == "localhost" or name.endswith(".local"):
        return True
    try:
        address = ip_address(name)
    except ValueError:
        return False
    return any(address in network for network in _LOCAL_NETWORKS)


def _account(base, path, body):
    base = base.strip().rstrip("/")
    url = urllib.parse.urlsplit(base)
    # Match the app's loopback and LAN exceptions for development and self-hosting.
    if not url.hostname or (url.scheme != "https" and not (url.scheme == "http" and _local_host(url.hostname))):
        raise InsecureServer("Use HTTPS to send a password outside your local network.")
    return request_json(base + path, body)


def sign_in(base, user, password, device, code=None):
    """Trades an account's password for a token for this device. The password is not kept.

    `code` is the two-factor code or a recovery code. Send it only after the server asked for
    one (`SecondFactor.ASKED`): servers without two-factor refuse fields they do not know."""
    body = {"user": user, "password": password, "device": device}
    code = (code or "").strip()
    if code:
        body["code"] = code
    try:
        return _account(base, "/api/accounts/tokens", body)
    except ServerError as error:
        if error.asks_code:
            error.second_factor = (
                SecondFactor.LOCKED if error.status == HTTPStatus.TOO_MANY_REQUESTS
                else SecondFactor.REFUSED if code
                else SecondFactor.ASKED
            )
        raise


def sign_up(base, user, password, display, device):
    """Creates an account and returns its first device token."""
    body = {"user": user, "password": password, "device": device}
    if display:
        body["display"] = display
    return _account(base, "/api/accounts", body)


COMPANIONS = ("aki", "ankilope", "cow", "anki_tan", "none")

# Tells the server this add-on shows locked companions, so it refuses one still locked.
SHOWS_LOCKS = {"X-AnkiQuest-Companions": "milestones"}

# Sent with every request: the companions this add-on draws, so the inbox leaves out moments
# about any other.
DRAWS = {"X-AnkiQuest-Companion-Art": ", ".join(companion for companion in COMPANIONS if companion != "none")}


def _companion(answer):
    choice = answer["companion"]
    return choice if choice in COMPANIONS else "aki"


class Client:
    def __init__(self, url, user, token, language="en"):
        self.base = url.strip().rstrip("/")
        self.name = user.strip()
        self.user = urllib.parse.quote(self.name, safe="")
        self.token = token.strip()
        self.language = language

    @property
    def configured(self):
        return bool(self.base and self.user and self.token)

    def _request(self, path, body=None, method=None, extra=None):
        headers = {**DRAWS, **(extra or {}), "Accept-Language": self.language}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return request_json(self.base + path, body, headers, method=method)

    def capabilities(self):
        """The features this server names at /api/capabilities."""
        return self.server_info()[0]

    def server_info(self):
        """The features this server names at /api/capabilities and its `public_url`, the main
        address, when it names one (else None)."""
        answer = request_json(self.base + "/api/capabilities")
        features = answer.get("features") if isinstance(answer, dict) else None
        url = answer.get("public_url") if isinstance(answer, dict) else None
        return (
            frozenset(name for name in features or () if isinstance(name, str)),
            url if isinstance(url, str) else None,
        )

    def rank(self, previous, week=None):
        """The weekly order, and how this player moved since `previous`, the order seen in
        competition `week` (from an earlier answer; the server ignores a change across weeks)."""
        body = {"previous": list(previous or [])}
        if isinstance(week, int) and not isinstance(week, bool):
            body["week"] = week
        return self._request("/api/rank/" + self.user, body)

    def profile(self):
        return self._request("/api/profile/" + self.user)

    def devices(self):
        """This player's signed-in devices; answers only with a working token, so it also checks one."""
        return self._request("/api/devices/" + self.user)

    def sign_in_methods(self):
        """How this player signs in: `sign_in` (absent from older servers), `password`, `providers`."""
        return self._request("/api/sign-in/" + self.user)

    def set_password(self, password):
        """Sets a first password with this device's token alone, for a player whose `sign_in` is
        `token_only`; answers as sign_in_methods."""
        body = {"action": "password", "password": password, "sign_out_others": False}
        return self._request("/api/sign-in/" + self.user, body)

    def leaderboard(self, period="week", scope="friends"):
        """The server's order and XP for this board and period."""
        return self._request("/api/leaderboard?" + urllib.parse.urlencode({"period": period, "scope": scope}))

    def companion(self):
        return _companion(self._request("/api/companion/" + self.user))

    def set_companion(self, companion):
        if companion not in COMPANIONS:
            raise ValueError("Unknown study companion")
        return _companion(self._request("/api/companion/" + self.user, {"companion": companion}, extra=SHOWS_LOCKS))

    def unlocks(self):
        """`{"unlocks": [...], "progress": {...}}`: the companions this player has unlocked and
        how far they are toward the others."""
        return self._request("/api/unlocks/" + self.user)

    def unlock(self, unlock):
        """Asks for a chibi the player found; the server grants it once its base is unlocked and
        answers as `unlocks`."""
        return self._request("/api/unlocks/" + self.user, {"unlock": unlock})

    def deck_settings(self):
        return self._request("/api/decks/" + self.user)

    def save_deck_settings(self, shared, unshared, recipients, nudges=None, celebrations=None):
        decks = [
            {"id": deck, "enabled": True, "recipients": list(recipients)} for deck in shared
        ]
        decks += [{"id": deck, "enabled": False, "recipients": []} for deck in unshared]
        body = {"decks": decks}
        if nudges is not None:
            body["nudges"] = bool(nudges)
        if celebrations is not None:
            body["celebrations"] = bool(celebrations)
        return self._request("/api/decks/" + self.user, body)

    def shared_decks(self):
        settings = self.deck_settings()
        return sorted(deck["id"] for deck in settings["decks"] if deck["enabled"])

    def upload(self, reviews, rollover_hour, silent, deleted=(), decks=None, clock_offset=None, catalog=False):
        body = {
            "reviews": reviews,
            "clock": {
                "offset_west_min": offset_west_min() if clock_offset is None else clock_offset,
                "rollover_hour": rollover_hour,
            },
            "silent": silent,
            "deleted": list(deleted),
        }
        if decks is not None:
            body["decks"] = decks
            body["catalog"] = catalog
        return self._request(
            "/api/reviews/" + self.user,
            body,
        )


def reconcile(window_rows, recent, known, mark):
    present = {r[0] for r in window_rows}
    deleted = sorted(recent - present) if mark else []
    restored = [r for r in window_rows if r[0] <= known and r[0] not in recent]
    return present, deleted, restored


def check_deletes(db, present, candidates):
    """Check the raw revlog before deleting, including rows ineligible for upload."""
    deleted = []
    for start in range(0, len(candidates), DELETE_QUERY_SIZE):
        ids = candidates[start:start + DELETE_QUERY_SIZE]
        placeholders = ",".join("?" for _ in ids)
        found = {row[0] for row in db.all("select id from revlog where id in (%s)" % placeholders, *ids)}
        present.update(found)
        deleted.extend(review for review in ids if review not in found)
    if len(deleted) > MAX_DELETES:
        print("ankiquest: suppressed a bulk deletion of %d reviews" % len(deleted))
        return []
    return deleted
