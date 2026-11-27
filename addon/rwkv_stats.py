"""The RWKV statistics on the deck browser, as AnkiQuest-Android's statistics show them (#489).

The definitions are Pedrubik2000's desktop add-on anki-rwkv-forecast, kept in
AnkiquestRwkvForecast on Android: every number means "if you stop reviewing now". The block
appears only while the backend can forecast: its RwkvOfflineForecast call exists on the
RWKV Anki forks, and answers `available` once a model is loaded. Without it — plain Anki,
no model — nothing is shown, exactly as the phone app hides its panel.
"""

import enum
import math
from html import escape
from typing import NamedTuple

# The add-on's `near_margin`: "near" is recall from the target up to this far above it.
NEAR_MARGIN = 0.03

# The chart measures recall in 1% buckets; the lowest holds every card at or below it.
LOWEST = 50
HIGHEST = 100

# Float recall such as 0.9 is 0.8999999; this keeps it in the 90% bucket.
ROUNDING = 1e-4

# The backend's code for the next day rollover.
ROLLOVER = -1

# The deck-browser block holds the collection while it forecasts; on Android the deck list
# skips the forecast above this many review cards.
MAX_CARDS = 3000

class Band(enum.Enum):
    """The chart's three stacks, and the forecast's three counts."""

    DUE = "due"
    NEAR = "near"
    SAFE = "safe"


# The times the backend projects recall to: now, in 1 h, in 3 h, at the next rollover.
OFFSETS = (0, 3600, 3 * 3600, ROLLOVER)

NOW = 0
IN_1H = 1
IN_3H = 2
TOMORROW = 3


class Recall:
    """One review card's RWKV recall, one value per offset, and the recall it is due under."""

    __slots__ = ("card_id", "target", "recall")

    def __init__(self, card_id, target, recall):
        self.card_id = card_id
        self.target = target
        self.recall = tuple(recall)

    def at(self, offset):
        return self.recall[offset]

    def band(self, offset):
        return band(self.at(offset), self.target)


def band(recall, target):
    """Due below the target, near within NEAR_MARGIN above it, safe beyond."""
    if recall < target:
        return Band.DUE
    if recall < target + NEAR_MARGIN:
        return Band.NEAR
    return Band.SAFE


Forecast = NamedTuple("Forecast", [
    (name, int) for name in ("due", "near", "safe", "in_1h", "in_3h", "by_tomorrow")
])


def forecast(cards):
    """Due, near and safe now, and the due cards later, as the forecast's two lines print them."""
    now = {band: 0 for band in Band}
    for card in cards:
        now[card.band(NOW)] += 1
    later = [card for card in cards if card.band(NOW) is not Band.DUE]

    def due_at(offset, rows):
        return sum(1 for card in rows if card.band(offset) is Band.DUE)

    return Forecast(
        now[Band.DUE], now[Band.NEAR], now[Band.SAFE],
        due_at(IN_1H, later), due_at(IN_3H, later),
        # "by tomorrow" counts every card due then, those due now included.
        due_at(TOMORROW, cards),
    )


def percent(recall):
    """The bucket percent of `recall`: its floor in whole percent, clamped to the chart."""
    return min(HIGHEST, max(LOWEST, int(math.floor(recall * 100 + ROUNDING))))


class Chart(NamedTuple):
    """The recall chart: its buckets stacked by band, the cards below target, and the targets."""

    buckets: list
    below: int
    total: int
    targets: set


def chart(cards):
    """The buckets of the recall chart, each stacked by band, with the cards below target."""
    by_percent = {}
    below = 0
    targets = set()
    for card in cards:
        if card.at(NOW) < card.target:
            below += 1
        targets.add(card.target)
        row = by_percent.setdefault(percent(card.at(NOW)), {band: 0 for band in Band})
        row[card.band(NOW)] += 1
    buckets = []
    for value in range(LOWEST, HIGHEST + 1):
        row = by_percent.get(value, {band: 0 for band in Band})
        buckets.append((value, row[Band.DUE], row[Band.NEAR], row[Band.SAFE]))
    return Chart(buckets, below, len(cards), targets)


def below_share(below, total):
    """The share of cards below their target, from 0 to 1."""
    return below / total if total else 0.0


def forecast_lines(counts, tr):
    """The forecast's two lines, translated before their numbers fill them."""
    now = tr("due %d | near %d | safe %d") % (counts.due, counts.near, counts.safe)
    later = tr("due %d · +%d in 1 h · +%d in 3 h · %d by tomorrow") % (
        counts.due, counts.in_1h, counts.in_3h, counts.by_tomorrow
    )
    return now, later


def below_line(below, total, targets, plural, percent_format):
    """The chart's caption: "X of Y cards (Z%) below 90%", or "...below their desired
    retention" where the cards carry more than one target. The target arrives as a value, so
    the plural choice stays a translation key."""
    share = percent_format(below_share(below, total))
    if len(targets) == 1:
        one, other = "%d of %d card (%s) below %s", "%d of %d cards (%s) below %s"
        values = (below, total, share, percent_format(next(iter(targets))))
    else:
        one, other = "%d of %d card (%s) below its desired retention", "%d of %d cards (%s) below their desired retention"
        values = (below, total, share)
    return plural(one, other, total) % values


def _rows_from(response):
    """The card rows of a backend answer, both the protobuf and a dict for tests."""
    if response is None:
        return False, []
    if isinstance(response, dict):
        available = response.get("available")
        cards = response.get("cards")
    else:
        available = getattr(response, "available", None)
        cards = getattr(response, "cards", None)
    if not available:
        return False, []
    if isinstance(cards, dict):
        cards = cards.get("cards") or []
    return True, list(cards or [])


def _field(row, name):
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _recalls_from(response):
    """Recall objects from a backend answer; a card with a value missing at any offset drops."""
    available, cards = _rows_from(response)
    if not available:
        return []
    rows = []
    for row in cards:
        recall = _field(row, "recall")
        target = _field(row, "target_retention")
        if target is None or recall is None or len(list(recall)) != len(OFFSETS):
            continue
        rows.append(Recall(_field(row, "card_id"), target, list(recall)))
    return rows


def too_large(count):
    """Whether the deck browser skips the forecast on this many review cards."""
    return count > MAX_CARDS


def recalls(col):
    """Every review card's RWKV recall, or None while the backend cannot forecast."""
    # Plain Anki has no RWKV backend call; a failing call is a real error again.
    try:
        response = col._backend.rwkv_offline_forecast(search="", offsets_secs=list(OFFSETS))
    except AttributeError:
        return None
    return _recalls_from(response) or None


STYLE = """<style>
#aq-rwkv{--rwkv-due:#D32F2F;--rwkv-near:#EF6C00;--rwkv-safe:#2E7D32;--rwkv-axis:#666666;
--rwkv-line:#e5e5e5;--rwkv-bg:#fff;--rwkv-text:#3c3c3c;--rwkv-muted:#6a6a6a;
max-width:680px;margin:1em auto 0;text-align:left;color:var(--rwkv-text);background:var(--rwkv-bg);
border:2px solid var(--rwkv-line);border-bottom-width:5px;border-radius:12px;padding:8px 12px;
font:600 13px/1.35 "Nunito","Varela Round","Segoe UI Variable Display","Segoe UI",system-ui,sans-serif}
.nightMode #aq-rwkv,.night-mode #aq-rwkv,.night_mode #aq-rwkv{--rwkv-due:#EF5350;--rwkv-near:#FFA726;
--rwkv-safe:#66BB6A;--rwkv-axis:#AAAAAA;--rwkv-line:#1e1f22;--rwkv-bg:#2b2d31;--rwkv-text:#f2f3f5;
--rwkv-muted:#b5bac1}
#aq-rwkv .rwkv-head{font-size:15px;font-weight:800}
#aq-rwkv .rwkv-note{color:var(--rwkv-muted);font-weight:600;font-size:12px}
#aq-rwkv .rwkv-bar{display:flex;align-items:flex-end;gap:1px;margin:8px 0 2px 0;height:96px;border-bottom:1px solid var(--rwkv-axis)}
#aq-rwkv .rwkv-col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;min-width:0}
#aq-rwkv .rwkv-col span{display:block}
#aq-rwkv .rwkv-bar{position:relative}
#aq-rwkv .rwkv-target{position:absolute;top:0;bottom:0;width:1px;background:var(--rwkv-due)}
#aq-rwkv .rwkv-axis{position:relative;height:14px;margin-top:2px;color:var(--rwkv-axis);font-size:10px}
#aq-rwkv .rwkv-axis span{position:absolute;transform:translateX(-50%)}
</style>"""


def _scaled(count, top):
    return 96 * count / top if top else 0


# The axis labels every bucket that ends in 0 as "p%", the first reading "50%".
AXIS_STEP = 10


def _at_bucket(value):
    """Where `value` sits across the chart's width, as a percent of its span."""
    return (value - LOWEST) / (HIGHEST - LOWEST) * 100


def html_rows(cards, tr, plural, percent_format):
    """The block for the deck browser: the two forecast lines and the recall chart."""
    marks = chart(cards)
    top = max(sum(row[1:]) for row in marks.buckets) or 1
    bars = []
    for _value, *counts in marks.buckets:
        parts = "".join(
            '<span style="display:block;height:%dpx;background:var(--rwkv-%s)"></span>'
            % (_scaled(count, top), band.value)
            for band, count in zip((Band.SAFE, Band.NEAR, Band.DUE), reversed(counts))
        )
        bars.append('<div class="rwkv-col">%s</div>' % parts)

    # A vertical line at each desired retention, as Android's chart draws them.
    targets = "".join(
        '<div class="rwkv-target" style="left:%.1f%%"></div>' % (_at_bucket(percent(value) - 0.5))
        for value in sorted(marks.targets)
    )

    def line(text):
        return "<div>%s</div>" % text

    axis = "".join(
        '<span style="left:%.1f%%%s">%s</span>'
        % (_at_bucket(value), ";transform:translateX(-100%)" if value == HIGHEST else "",
           ("≤%d%%" % LOWEST) if value == LOWEST else "%d%%" % value)
        for value in range(LOWEST, HIGHEST + 1, AXIS_STEP)
    )
    caption = below_line(marks.below, marks.total, marks.targets, plural, percent_format)
    now, later = forecast_lines(forecast(cards), tr)
    return (
        '<div class="rwkv-head">%s <span class="rwkv-note">%s</span></div>'
        % (escape(tr("RWKV forecast")), escape(tr("if you stop reviewing now")))
        + line(escape(now))
        + line(escape(later))
        + '<div class="rwkv-head">%s</div>' % escape(tr("RWKV recall now"))
        + '<div class="rwkv-bar" role="img" aria-label="%s">%s%s</div>'
        % (escape(caption), "".join(bars), targets)
        + '<div class="rwkv-axis">%s</div>' % axis
        + line(escape(caption))
    )


def block(col, tr, plural, percent_format):
    """The whole RWKV block, or empty when the backend cannot forecast or the collection is
    too large for the deck browser's render."""
    try:
        if too_large(col.db.scalar("select count() from cards where type = 2")):
            return ""
    except Exception:
        return ""
    cards = recalls(col)
    if cards is None:
        return ""
    return '<div id="aq-rwkv">%s</div>' % html_rows(cards, tr, plural, percent_format)
