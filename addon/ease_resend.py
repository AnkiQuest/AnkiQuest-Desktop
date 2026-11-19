"""One resend of the whole review history with the answer button (`ease`), so a server that
counts a lapse by the button corrects the reviews it stored without one (hill, 2026-11-19).

The resend goes only to a server that names FEATURE at /api/capabilities: an older server
drops the button, and resending to it would use up the one resend. The state is kept per
server account with the upload cursor."""

from enum import Enum

from .client import MAX_PENDING

# The capability of a server that stores the button of each review.
FEATURE = "review_ease"
# Where the state is kept in an account's upload record.
KEY = "ease_resend"


class Resend(Enum):
    """Where this account stands with the resend."""

    # Every review this server has from here came with the button.
    NOT_NEEDED = "not_needed"
    # Owed: earlier uploads left the button out, or the server could not store it yet.
    PENDING = "pending"
    # An upload that resends the history is running.
    SENDING = "sending"
    # The whole history was resent with the button.
    DONE = "done"


class Check(Enum):
    """What an upload that owed the resend found."""

    # The server does not store the button yet.
    UNSUPPORTED = "unsupported"
    # The upload itself sent the whole history with the button.
    COVERED = "covered"
    # The upload resent the whole history.
    RESENT = "resent"
    # Asking the server or resending failed; the reviews themselves were uploaded.
    FAILED = "failed"


def load(saved):
    """The stored state; a missing or unknown one is owed, and an interrupted one is owed again."""
    try:
        resend = Resend(saved.get(KEY))
    except ValueError:
        return Resend.PENDING
    if resend is Resend.SENDING:
        return Resend.PENDING
    return resend


def save(saved, resend):
    saved[KEY] = resend.value


def start(resend):
    """An upload that may resend begins."""
    if resend is Resend.PENDING:
        return Resend.SENDING
    return resend


def finish(resend, check):
    """The upload that began with `start` was accepted."""
    if resend is not Resend.SENDING:
        return resend
    if check is Check.RESENT:
        return Resend.DONE
    if check is Check.COVERED:
        return Resend.NOT_NEEDED
    return Resend.PENDING


def fail(resend):
    """The upload that began with `start` failed or was cut short."""
    if resend is Resend.SENDING:
        return Resend.PENDING
    return resend


def send_history(read, send):
    """Sends every row `read` returns, oldest first, in batches of at most MAX_PENDING rows (the
    server's limit per upload). `read(after)` returns the rows after id `after`, at most one
    batch. Returns how many rows went."""
    after = count = 0
    while True:
        rows = read(after)
        if not rows:
            return count
        send(rows)
        count += len(rows)
        after = rows[-1][0]
        if len(rows) < MAX_PENDING:
            return count
