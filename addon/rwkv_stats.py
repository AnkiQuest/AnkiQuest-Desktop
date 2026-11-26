"""The RWKV statistics on the deck browser, as AnkiQuest-Android's statistics show them (#489).

The definitions are Pedrubik2000's desktop add-on anki-rwkv-forecast, kept in
AnkiquestRwkvForecast on Android: every number means "if you stop reviewing now". The block
appears only while the backend can forecast: its RwkvOfflineFront call exists on the
RWKV Anki forks, and answers `available` once a model is loaded. Without it — plain Anki,
no model — nothing is shown, exactly as the phone app hides its panel.
"""

import math
from html import escape

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
        return "due"
    if recall < target + NEAR_MARGIN:
        return "near"
    return "safe"


def forecast(cards):
    """Due, near and safe now, and the due cards later, as the forecast line prints them."""
    now = {}
    for card in cards:
        now[card.band(NOW)] = now.get(card.band(NOW), 0) + 1
    later = [card for card in cards if card.band(NOW) != "due"]

    def due_at(offset, rows):
        return sum(1 for card in rows if card.band(offset) == "due")

    return {
        "due": now.get("due", 0),
        "near": now.get("near", 0),
        "safe": now.get("safe", 0),
        "in_1h": due_at(IN_1H, later),
        "in_3h": due_at(IN_3H, later),
        # "by tomorrow" counts every card due then, those due now included.
        "by_tomorrow": due_at(TOMORROW, cards),
    }


def percent(recall):
    """The bucket percent of `recall`: its floor in whole percent, clamped to the chart."""
    return min(HIGHEST, max(LOWEST, int(math.floor(recall * 100 + ROUNDING))))


def chart(cards):
    """The buckets of the recall chart, each stacked by band, with the cards below target."""
    by_percent = {}
    below = 0
    targets = set()
    for card in cards:
        if card.at(NOW) < card.target:
            below += 1
        targets.add(card.target)
        row = by_percent.setdefault(percent(card.at(NOW)), [0, 0, 0])
        row["due near safe".split().index(card.band(NOW))] += 1
    buckets = []
    for value in range(LOWEST, HIGHEST + 1):
        due, near, safe = by_percent.get(value, (0, 0, 0))
        buckets.append((value, due, near, safe))
    return buckets, below, len(cards), targets


def below_share(below, total):
    """The share of cards below their target, from 0 to 1."""
    return below / total if total else 0.0


def _whole_percent(value):
    """A share from 0 to 1 as a percent, at most one decimal: 0.5 → "50%", 0.629 → "62.9%"."""
    return ("%.1f" % (value * 100)).rstrip("0").rstrip(".") + "%"


def forecast_text(forecast):
    """The two forecast lines, worded as the add-on's."""
    return (
        "due %(due)d | near %(near)d | safe %(safe)d" % forecast + "\n"
        + "due %(due)d · +%(in_1h)d in 1 h · +%(in_3h)d in 3 h · %(by_tomorrow)d by tomorrow" % forecast
    )


def below_line(below, total, targets, plural=None):
    """The chart's caption: "X of Y cards (Z%) below 90%", or "...below their desired
    retention" where the cards carry more than one target. The target arrives as a value, so
    the plural choice stays a translation key."""
    if plural is None:
        from .language import plural as plural
    share = _whole_percent(below_share(below, total))
    if len(targets) == 1:
        one, other = "%d of %d card (%s) below %s", "%d of %d cards (%s) below %s"
        values = (below, total, share, _whole_percent(next(iter(targets))))
    else:
        one, other = "%d of %d card (%s) below their desired retention", "%d of %d cards (%s) below their desired retention"
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
    try:
        response = col._backend.rwkv_offline_forecast(search="", offsets_secs=list(OFFSETS))
        rows = _recalls_from(response)
    except Exception:
        return None
    return rows or None


STYLE = """<style>
#aq-rwkv{--rwkv-due:#D32F2F;--rwkv-near:#EF6C00;--rwkv-safe:#2E7D32;--rwkv-axis:#666666;
--rwkv-line:#e5e5e5;--rwkv-bg:#fff;--rwkv-text:#3c3c3c;--rwkv-muted:#777;
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
#aq-rwkv .rwkv-axis{display:flex;margin-top:2px;color:var(--rwkv-axis);font-size:10px}
#aq-rwkv .rwkv-axis span{flex:1;text-align:right;transform:translateX(50%)}
</style>"""


def _scaled(count, top):
    return 96 * count / top if top else 0


def html_rows(cards, tr):
    """The block for the deck browser: the forecast line and the recall chart."""
    from .language import plural

    buckets, below, total, targets = chart(cards)
    top = max(row[1] + row[2] + row[3] for row in buckets) or 1
    bars = []
    for _value, due, near, safe in buckets:
        parts = "".join(
            '<span style="display:block;height:%dpx;background:var(--rwkv-%s)"></span>' % (_scaled(count, top), name)
            for name, count in (("safe", safe), ("near", near), ("due", due))
        )
        bars.append('<div class="rwkv-col">%s</div>' % parts)

    def line(text):
        return "<div>%s</div>" % text

    axis = "".join("<span>%d%%</span>" % value for value in range(LOWEST, HIGHEST + 1, 25))
    return (
        '<div class="rwkv-head">%s <span class="rwkv-note">%s</span></div>'
        % (escape(tr("RWKV forecast")), escape(tr("if you stop reviewing now")))
        + line(escape(forecast_text(forecast(cards))))
        + '<div class="rwkv-head">%s</div>' % escape(tr("RWKV recall now"))
        + '<div class="rwkv-bar">%s</div>' % "".join(bars)
        + '<div class="rwkv-axis">%s</div>' % axis
        + line(escape(below_line(below, total, targets, plural)))
    )


def block(col, tr):
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
    return '<div id="aq-rwkv">%s</div>' % html_rows(cards, tr)
