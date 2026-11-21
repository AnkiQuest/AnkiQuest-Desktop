"""The Today card that asks a player who signs in only with a device token to set a password
(`"sign_in": "token_only"` in GET /api/sign-in/<user>, AnkiQuest-Server docs/mobile-api.md), so
they keep their account once the server operator removes their token from the configuration.
Servers without `sign_in` never show it. The app shows the same card with the same wording."""

from enum import Enum

# How long Not now hides the card on this computer.
SNOOZE_MS = 3 * 24 * 60 * 60 * 1000
SNOOZED_KEY = "ankiquestPasswordPromptSnoozed"
PASSWORD_LENGTH = range(10, 257)


class _SignIn(Enum):
    """How the player can sign in on a new device (the server's accounts::SignIn)."""
    PASSWORD = "password"
    PROVIDER = "provider"
    TOKEN_ONLY = "token_only"


def _sign_in(methods):
    """`sign_in` from the sign-in methods; None from a server without it or with a new value."""
    value = methods.get("sign_in") if isinstance(methods, dict) else None
    try:
        return _SignIn(value)
    except ValueError:
        return None


def _key(account):
    # The server and the player, never the token.
    return "%s %s" % (account[0], account[1])


def _snoozed(prefs, account, now):
    """Whether Not now still hides the card for `account` ([base, user, token])."""
    at = (prefs.get(SNOOZED_KEY) or {}).get(_key(account))
    return isinstance(at, int) and now - at < SNOOZE_MS


def _snooze(prefs, account, now):
    stored = dict(prefs.get(SNOOZED_KEY) or {})
    stored[_key(account)] = now
    prefs[SNOOZED_KEY] = stored


def _problem(password, repeat):
    """What is wrong with the new password, checked as the server would, or None."""
    if len(password) not in PASSWORD_LENGTH:
        return "Use 10 to 256 characters."
    if repeat != password:
        return "The two passwords are not the same."
    return None
