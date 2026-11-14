"""The hidden cow companion, unlocked by tapping Ankilope in the companion picker.

The rule (how many taps, how far apart) is defined in tests/fixtures/companion_unlock.json;
tests keep `TAPS` and `MAX_GAP_MS` equal to it. An unlock is kept here per account until the
server has it, so one made offline is sent later."""

from enum import Enum

from . import moods

FEATURE = "companion_unlocks"

TAPS = 9
MAX_GAP_MS = 2000

# Profile key: account -> {unlock id: Delivery value}.
UNLOCKS_KEY = "ankiquestUnlocks"


class Delivery(Enum):
    """Whether the server has an unlock made on this computer."""
    PENDING = "pending"
    SENT = "sent"


class Taps:
    """Counts taps on Ankilope in a row; a tap elsewhere or a long gap starts again."""

    def __init__(self):
        self._run = 0
        self._last_ms = None

    def tap(self, choice, at_ms):
        """Records a tap on `choice`; True on the tap that completes the run."""
        if choice != moods.ANKILOPE_ID:
            self._run, self._last_ms = 0, None
            return False

        # A late tap is the first of a new run.
        late = self._last_ms is not None and at_ms - self._last_ms > MAX_GAP_MS
        self._run = 1 if late else self._run + 1
        self._last_ms = at_ms
        if self._run < TAPS:
            return False
        self._run, self._last_ms = 0, None
        return True


def account(api):
    """The key unlocks are kept under: the server and player, whatever the device token."""
    return "%s|%s" % (api.base, api.name)


def _kept(prefs, key):
    found = (prefs.get(UNLOCKS_KEY) or {}).get(key)
    return found if isinstance(found, dict) else {}


def _store(prefs, key, unlocks):
    every = dict(prefs.get(UNLOCKS_KEY) or {})
    every[key] = unlocks
    prefs[UNLOCKS_KEY] = every


def unlocked(prefs, key):
    """Every unlock this computer knows for the account, sent or not."""
    return set(_kept(prefs, key))


def pending(prefs, key):
    """Unlocks made here that the server does not have yet, sorted."""
    return sorted(unlock for unlock, delivery in _kept(prefs, key).items() if delivery == Delivery.PENDING.value)


def record(prefs, key, unlock):
    """Keeps an unlock made here until the server has it."""
    kept = dict(_kept(prefs, key))
    if kept.get(unlock) != Delivery.SENT.value:
        kept[unlock] = Delivery.PENDING.value
    _store(prefs, key, kept)


def settle(prefs, key, server):
    """Marks what the server lists as sent, including unlocks made on other devices."""
    kept = dict(_kept(prefs, key))
    for unlock in server:
        kept[unlock] = Delivery.SENT.value
    _store(prefs, key, kept)


def _listed(answer):
    found = answer.get("unlocks") if isinstance(answer, dict) else None
    return [unlock for unlock in found or () if isinstance(unlock, str)]


def fetch(api, features):
    """The server's unlocks, or None when it has no unlocks. Runs in the background."""
    if FEATURE not in features:
        return None
    return _listed(api.unlocks())


def send(api, unlocks):
    """Sends unlocks made here and answers the server's list, or None when the server has no
    unlocks. Runs in the background."""
    if FEATURE not in api.capabilities():
        return None
    answer = None
    for unlock in unlocks:
        answer = api.unlock(unlock)
    return _listed(answer) if answer is not None else _listed(api.unlocks())
