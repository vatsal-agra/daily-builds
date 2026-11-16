"""Self-contained HTML renderers (no external assets): a month calendar and a meeting-slot view."""
import html
from datetime import date, datetime, timedelta

from .dates import DAY_NAMES, MONTH_NAMES, days_in_month
from .tz import UTC, get_zone

_CSS = """
:root{--bg:#f6f4ef;--card:#fffdf8;--ink:#1d2433;--mute:#7b8498;--line:#e4dfd3;--accent:#c2410c;
--today:#fff1e0;--off:#faf7f0;--shadow:0 1px 2px rgba(29,36,51,.06),0 8px 24px rgba(29,36,51,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#10141c;--card:#171c27;--ink:#e8ecf4;--mute:#8d97ad;
--line:#262d3d;--accent:#fb923c;--today:#2a2218;--off:#131822;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:32px 16px}
.wrap{max-width:1040px;margin:0 auto}h1{font:700 28px/1.2 ui-serif,Georgia,serif;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--mute);margin:0 0 20px}
.grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);
border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}
.dow{background:var(--card);padding:8px 10px;font-size:12px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.06em}
.day{background:var(--card);min-height:112px;padding:6px 6px 8px;min-width:0}.day.off{background:var(--off)}.day.off .n{color:var(--mute)}
.day.today{background:var(--today)}.n{font-weight:600;font-size:13px;margin:0 2px 4px}
.ev{display:block;font-size:12px;line-height:1.25;padding:3px 6px;margin:2px 0;border-radius:6px;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis;border-left:3px solid var(--c);background:color-mix(in srgb,var(--c) 14%,transparent)}
.ev b{font-weight:600;margin-right:4px;font-variant-numeric:tabular-nums}.ev.ov{font-style:italic}
.more{font-size:11px;color:var(--mute);padding:0 6px}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:16px;font-size:13px;color:var(--mute)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;background:var(--c)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:18px 20px;margin-bottom:16px}
.row{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;margin:8px 0}
.who{font-weight:600;font-size:14px}.who small{display:block;color:var(--mute);font-weight:400;font-size:12px}
.bar{position:relative;height:26px;background:var(--off);border-radius:6px;border:1px solid var(--line);overflow:hidden}
.seg{position:absolute;top:0;bottom:0}.work{background:color-mix(in srgb,#16a34a 30%,transparent)}.str{background:color-mix(in srgb,#ca8a04 22%,transparent)}
.busy{background:repeating-linear-gradient(45deg,color-mix(in srgb,#dc2626 55%,transparent) 0 4px,transparent 4px 8px)}
.pick{position:absolute;top:-2px;bottom:-2px;border:2px solid var(--accent);border-radius:6px;background:color-mix(in srgb,var(--accent) 18%,transparent);pointer-events:none}
.axis{display:grid;grid-template-columns:150px 1fr;gap:12px}.ticks{display:flex;justify-content:space-between;font-size:11px;color:var(--mute);font-variant-numeric:tabular-nums}
.slot{padding:10px 0;border-top:1px solid var(--line)}.slot:first-of-type{border-top:0}.slot h3{margin:0 0 4px;font-size:15px}
.slot .sc{float:right;color:var(--mute);font-size:12px}.chip{display:inline-block;font-size:12px;border-radius:99px;padding:1px 9px;
margin:2px 4px 2px 0;border:1px solid var(--line);background:var(--off)}.chip.s{border-color:var(--accent);color:var(--accent)}
@media(max-width:640px){.day{min-height:78px}.ev b{display:none}.row,.axis{grid-template-columns:96px 1fr}}
"""
_PALETTE = ["#c2410c", "#2563eb", "#059669", "#9333ea", "#d97706", "#db2777", "#0891b2", "#65a30d"]


def _page(title, body):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><div class=wrap>{body}</div></body></html>")


def render_month(cal, year, month, today=None, zone="UTC"):
    """HTML month grid for an ics.Calendar."""
    if not 1 <= month <= 12:
        raise ValueError("month must be 1..12")
    z = get_zone(zone)
    first = date(year, month, 1)
    grid0 = first - timedelta(days=first.weekday())
    nweeks = ((first.weekday() + days_in_month(year, month)) + 6) // 7
    grid1 = grid0 + timedelta(days=7 * nweeks)
    occ = cal.occurrences(datetime(grid0.year, grid0.month, grid0.day, tzinfo=UTC) - timedelta(days=1),
                          datetime(grid1.year, grid1.month, grid1.day, tzinfo=UTC) + timedelta(days=1))
    colors, per_day = {}, {}
    for o in occ:
        colors.setdefault(o.event.uid, _PALETTE[len(colors) % len(_PALETTE)])
        s, e = o.start, o.end
        if isinstance(s, datetime):
            sl = s.astimezone(z) if s.tzinfo else s
            el = e.astimezone(z) if e.tzinfo else e
            d0, d1 = sl.date(), (el - timedelta(microseconds=1)).date() if el > sl else sl.date()
            label = sl.strftime("%H:%M")
        else:
            d0, d1, label = s, (e - timedelta(days=1)), ""
            if d1 < d0:
                d1 = d0
        d = d0
        while d <= d1:
            per_day.setdefault(d, []).append((label if d == d0 else "", o))
            d += timedelta(days=1)
    cells = "".join(f"<div class=dow>{n[:3]}</div>" for n in DAY_NAMES)
    for i in range(7 * nweeks):
        d = grid0 + timedelta(days=i)
        cls = "day" + ("" if d.month == month else " off") + (" today" if today == d else "")
        evs = per_day.get(d, [])
        items = "".join(
            f"<span class='ev{' ov' if o.override else ''}' style='--c:{colors[o.event.uid]}' "
            f"title='{html.escape(o.event.summary)}'>"
            f"{'<b>' + label + '</b>' if label else ''}{html.escape(o.event.summary or '(no title)')}</span>"
            for label, o in evs[:4])
        more = f"<div class=more>+{len(evs) - 4} more</div>" if len(evs) > 4 else ""
        cells += f"<div class='{cls}'><div class=n>{d.day}</div>{items}{more}</div>"
    seen = {}
    for o in occ:
        seen.setdefault(o.event.uid, o.event.summary or o.event.uid)
    legend = "".join(f"<span><i style='--c:{colors[u]}'></i>{html.escape(n)}</span>" for u, n in seen.items())
    n_in = sum(1 for d, v in per_day.items() if d.month == month for _ in v)
    body = (f"<h1>{MONTH_NAMES[month - 1]} {year}</h1>"
            f"<p class=sub>{html.escape(cal.name or 'Calendar')} · {n_in} entries · times in {html.escape(str(getattr(z, 'key', 'UTC')))}</p>"
            f"<div class=grid>{cells}</div><div class=legend>{legend}</div>")
    return _page(f"{MONTH_NAMES[month - 1]} {year}", body)


def render_meeting(attendees, day, slots, zone="UTC"):
    """HTML view: one 24 h bar per attendee (work/busy) with each proposed slot outlined."""
    from .scheduler import Interval, intersect
    z = get_zone(zone)
    if isinstance(day, datetime) and day.tzinfo is not None:
        day = day.astimezone(z)          # the calendar day *in the display zone*
    start = datetime(day.year, day.month, day.day)   # always local midnight
    from .tz import resolve
    lo = resolve(start, z).astimezone(UTC)
    hi = resolve(start + timedelta(days=1), z).astimezone(UTC)
    span = (hi - lo).total_seconds()

    def pct(t):
        return max(0.0, min(100.0, (t - lo).total_seconds() / span * 100))

    def seg(i, cls):
        a, b = pct(i.start), pct(i.end)
        return f"<div class='seg {cls}' style='left:{a:.2f}%;width:{max(b - a, 0):.2f}%'></div>" if b > a else ""
    win = Interval(lo, hi)
    rows = ""
    for a in attendees:
        work = intersect(a.hours.intervals(a.zone, lo, hi), [win])
        stretch = (intersect(a.stretch.intervals(a.zone, lo, hi), [win]) if a.stretch is not None else [])
        busy = [i for i in a.busy_intervals(lo, hi) if i.end > lo and i.start < hi]
        picks = "".join(f"<div class=pick style='left:{pct(s.start):.2f}%;width:{pct(s.end) - pct(s.start):.2f}%'></div>"
                        for s in slots if s.start < hi and s.end > lo)
        zn = getattr(a.zone, "key", "UTC")
        rows += (f"<div class=row><div class=who>{html.escape(a.name)}<small>{html.escape(zn)}"
                 f"{' · optional' if a.optional else ''}</small></div><div class=bar>"
                 f"{''.join(seg(i, 'str') for i in stretch)}{''.join(seg(i, 'work') for i in work)}{''.join(seg(i, 'busy') for i in busy)}{picks}</div></div>")
    ticks = "".join(f"<span>{h:02d}</span>" for h in range(0, 25, 3))
    chart = (f"<div class=card><div class=axis><div></div><div class=ticks>{ticks}</div></div>{rows}</div>")
    cards = ""
    for s in slots:
        chips = "".join(
            f"<span class='chip{' s' if flag == 'stretch' else ''}'>{html.escape(n)} "
            f"{a.strftime('%a %H:%M')}–{b.strftime('%H:%M')}{' (stretch)' if flag == 'stretch' else ''}</span>"
            for n, (a, b, flag) in s.local.items())
        cards += (f"<div class=slot><span class=sc>score {s.score:.1f}</span>"
                  f"<h3>{s.start.astimezone(z).strftime('%a %b %d, %H:%M')}–{s.end.astimezone(z).strftime('%H:%M')}</h3>{chips}</div>")
    if not slots:
        cards = "<p class=sub>No common slot found.</p>"
    body = (f"<h1>Meeting finder</h1><p class=sub>{day.strftime('%A %B %d, %Y') if hasattr(day,'strftime') else day} · "
            f"bars are in {html.escape(str(getattr(z, 'key', 'UTC')))} · green = working hours, amber = stretch hours, hatched = busy, outlined = proposed</p>"
            f"{chart}<div class=card>{cards}</div>")
    return _page("Meeting finder", body)
