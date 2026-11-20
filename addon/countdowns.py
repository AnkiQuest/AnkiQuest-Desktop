"""Countdowns to the player's events and exams, kept in the synced setting `countdowns`.

The rules (days from the Anki day, the nearest event, the list order, the Anki search for the
cards left, cards a day) are the cases in tests/fixtures/countdowns.json, which the Android app
tests against too. The limits are the key's entry in tests/fixtures/synced_settings.json."""

from collections import namedtuple
from datetime import datetime, timedelta
from enum import Enum
import re

FEATURE = "countdowns"
CONFIG_KEY = "countdowns"

MAX_EVENTS = 20
MAX_NAME_CHARS = 60
MAX_DECK_CHARS = 200

DATE_FORMAT = "%Y-%m-%d"

# Exactly YYYY-MM-DD in ASCII digits: strptime alone also reads fullwidth digits.
_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Characters Anki's search treats as special inside a quoted deck name.
_SEARCH_SPECIAL = '\\"*_'


class State(Enum):
    UPCOMING = "upcoming"
    TOMORROW = "tomorrow"
    TODAY = "today"
    PAST = "past"


class PaceKind(Enum):
    PER_DAY = "per_day"
    DONE = "done"
    NONE = "none"


Event = namedtuple("Event", "name date deck")
Days = namedtuple("Days", "state days")
Pace = namedtuple("Pace", "kind cards")
# An account's list with signed-out events added, and the signed-out events that did not fit.
Imported = namedtuple("Imported", "account left")


def parse_date(text):
    """The date of a `YYYY-MM-DD` string, or None."""
    if not isinstance(text, str) or not _DATE_SHAPE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        return None


def usable_deck(deck):
    """Whether a countdown can name `deck`: Anki allows longer names than the server keeps."""
    return isinstance(deck, str) and bool(deck.strip()) and len(deck) <= MAX_DECK_CHARS


def _valid_event(found):
    if not isinstance(found, dict) or set(found) - {"name", "date", "deck"}:
        return False
    name, deck = found.get("name"), found.get("deck")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_CHARS:
        return False
    if deck is not None and not usable_deck(deck):
        return False
    return parse_date(found.get("date")) is not None


def valid(value):
    """Whether `value` is a countdown list the server would store."""
    return isinstance(value, list) and len(value) <= MAX_EVENTS and all(_valid_event(found) for found in value)


def events(value):
    """The events in a stored list; an unusable list counts as empty."""
    if not valid(value):
        return []
    return [Event(found["name"], found["date"], found.get("deck")) for found in value]


def stored(items):
    """The list as the setting keeps it."""
    return [{"name": event.name, "date": event.date, "deck": event.deck} for event in items]


def anki_today(now, day_start_hour):
    """The Anki day of local time `now`: its date once the day start hour is taken off."""
    return (now - timedelta(hours=day_start_hour)).date()


def days(today, event_date):
    left = (event_date - today).days
    if left < 0:
        return Days(State.PAST, left)
    if left == 0:
        return Days(State.TODAY, left)
    if left == 1:
        return Days(State.TOMORROW, left)
    return Days(State.UPCOMING, left)


def nearest(items, today):
    """The event with the fewest days that is not past; on a tie the first in the list."""
    best, best_days = None, None
    for event in items:
        found = days(today, parse_date(event.date))
        if found.state is State.PAST:
            continue
        if best_days is None or found.days < best_days.days:
            best, best_days = event, found
    return best


def ordered(items):
    """The list in settings: by date, on a tie in stored order."""
    return sorted(items, key=lambda event: event.date)


def search(deck, left):
    """The Anki search for the cards `deck` still has before an event `left` days away."""
    escaped = "".join("\\" + c if c in _SEARCH_SPECIAL else c for c in deck)
    return 'deck:"%s" -is:suspended (is:new OR is:learn OR prop:due<%d)' % (escaped, left)


def pace(left, remaining):
    """Cards a day up to the day before the event. `remaining` is None without a usable deck."""
    if remaining is None or left < 1:
        return Pace(PaceKind.NONE, None)
    if remaining == 0:
        return Pace(PaceKind.DONE, None)
    return Pace(PaceKind.PER_DAY, -(-remaining // left))


def headline(event, found, translate):
    texts = {
        State.UPCOMING: lambda: translate("%s in %d days") % (event.name, found.days),
        State.TOMORROW: lambda: translate("%s tomorrow") % event.name,
        State.TODAY: lambda: translate("%s today") % event.name,
        State.PAST: lambda: translate("%s is over") % event.name,
    }
    return texts[found.state]()


def pace_text(found, deck_label, plural, translate):
    """The pace line, or None. `plural(one, other, count)` picks the form."""
    if found.kind is PaceKind.DONE:
        return translate("Nothing left in %s before then") % deck_label
    if found.kind is PaceKind.PER_DAY:
        form = plural("~%d card a day to finish %s by then", "~%d cards a day to finish %s by then", found.cards)
        return form % (found.cards, deck_label)
    return None


def imported(account, device):
    """`account` with the events of `device` added in order, skipping one with the same name and
    date as an event already in the list; what does not fit is left. Cases: `import`."""
    merged, left = list(account), []
    for event in device:
        if any(kept.name == event.name and kept.date == event.date for kept in merged):
            continue
        if len(merged) >= MAX_EVENTS:
            left.append(event)
            continue
        merged.append(event)
    return Imported(merged, left)


def import_question(count, user, plural):
    """The offer to add `count` signed-out countdowns to `user`'s account. `plural(one, other,
    count)` picks the translated form; the one form names no count."""
    form = plural("Add the countdown you made while signed out to %s?",
                  "Add the %d countdowns you made while signed out to %s?", count)
    return form % user if count == 1 else form % (count, user)


def left_text(count, plural):
    """What is said about `count` countdowns that did not fit and stay on this computer."""
    form = plural("%d countdown did not fit and stays on this device.",
                  "%d countdowns did not fit and stay on this device.", count)
    return form % count


def first_date(today):
    """The date a new countdown starts on: a week from today."""
    return today + timedelta(days=7)
