"""Study time from the local review log: today, this week, this month, total and per study day.

    collection (revlog) ──load──▶ days per study day ──summarize──▶ StudyTime ──▶ progress_ui

AnkiQuest-Server's tests/fixtures/study_time.json pins the rule for this and the Android app
(AnkiquestStudyTime.kt). Plain Python, so the tests load it without Anki.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from .deck_completion import DAY_MS, study_day

MINUTE_MS = 60_000
HOUR_MINUTES = 60
EPOCH = date(1970, 1, 1)

# Time per study day, as AnkiQuest counts days (clients.json study_day). Answers only: manual
# (type 4) and rescheduled (type 5) entries are not study, as in the review heatmap. The upper
# bound leaves out reviews on a later day than today, which a clock moved back can leave.
DAYS_SQL = (
    "select (id - ?) / %d, sum(time) from revlog "
    "where id >= 0 and id < ? and ease > 0 and type < 4 group by 1" % DAY_MS
)


@dataclass(frozen=True)
class StudyTime:
    today: date
    today_ms: int
    week_ms: int
    month_ms: int
    total_ms: int
    study_days: int

    @property
    def average_ms(self):
        return self.total_ms // self.study_days if self.study_days else 0


def _date(day):
    return EPOCH + timedelta(days=day)


def summarize(today, days):
    """The totals from study day numbers to milliseconds; days after today are not counted."""
    shown = _date(today)
    counted = {day: ms for day, ms in days.items() if day <= today}

    # Weeks start on Monday; the month is today's calendar month.
    monday = today - shown.weekday()
    month = shown.replace(day=1)
    return StudyTime(
        today=shown,
        today_ms=counted.get(today, 0),
        week_ms=sum(ms for day, ms in counted.items() if day >= monday),
        month_ms=sum(ms for day, ms in counted.items() if _date(day).replace(day=1) == month),
        total_ms=sum(counted.values()),
        study_days=len(counted),
    )


def load(db, now_ms, offset_west_min, rollover_hour):
    """Read the review log with Anki's `db` (anything with `all(sql, *args)`)."""
    today = study_day(now_ms, offset_west_min, rollover_hour)
    shift = offset_west_min * 60_000 + rollover_hour * 3_600_000
    tomorrow = (today + 1) * DAY_MS + shift
    rows = db.all(DAYS_SQL, shift, tomorrow)
    return summarize(today, {int(day): int(ms or 0) for day, ms in rows})


def duration(ms, translate=lambda value: value):
    """Whole minutes, rounded down; hours and minutes from an hour on."""
    minutes = ms // MINUTE_MS
    if minutes < HOUR_MINUTES:
        return translate("%d min") % minutes
    return translate("%d h %d min") % (minutes // HOUR_MINUTES, minutes % HOUR_MINUTES)
