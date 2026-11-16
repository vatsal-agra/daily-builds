"""Calendar arithmetic written from first principles (no reliance on calendar/dateutil)."""
from datetime import date, timedelta

MO, TU, WE, TH, FR, SA, SU = range(7)
DAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
_MDAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def days_in_month(y, m):
    return 29 if (m == 2 and is_leap(y)) else _MDAYS[m - 1]


def days_in_year(y):
    return 366 if is_leap(y) else 365


def month_dates(y, m):
    first = date(y, m, 1)
    return [first + timedelta(days=i) for i in range(days_in_month(y, m))]


def year_dates(y):
    first = date(y, 1, 1)
    return [first + timedelta(days=i) for i in range(days_in_year(y))]


def week_start(d, wkst):
    """First day of the week (starting on weekday `wkst`) that contains d."""
    return d - timedelta(days=(d.weekday() - wkst) % 7)


def week1_start(y, wkst):
    """Start of week 1 of year y: the first wkst-week containing at least 4 days of y
    (equivalently, the week containing January 4th)."""
    return week_start(date(y, 1, 4), wkst)


def weeks_in_year(y, wkst):
    return (week1_start(y + 1, wkst) - week1_start(y, wkst)).days // 7


def week_of(d, wkst):
    """(week_year, week_number, weeks_in_that_week_year) of date d for week-start wkst."""
    y = d.year
    if d >= week1_start(y + 1, wkst):
        y += 1
    elif d < week1_start(y, wkst):
        y -= 1
    n = (d - week1_start(y, wkst)).days // 7 + 1
    return y, n, weeks_in_year(y, wkst)


def nth_weekday_in(d, scope):
    """Ordinal pair (n, -m) of d's weekday within its month or year.
    n counts from the start (1-based), -m from the end."""
    if scope == "month":
        n = (d.day - 1) // 7 + 1
        m = (days_in_month(d.year, d.month) - d.day) // 7 + 1
    else:
        yday = (d - date(d.year, 1, 1)).days + 1
        n = (yday - 1) // 7 + 1
        m = (days_in_year(d.year) - yday) // 7 + 1
    return n, -m


def yearday(d):
    return (d - date(d.year, 1, 1)).days + 1
