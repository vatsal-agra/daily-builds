import sys,traceback
import time as _time
sys.path.insert(0,'.')
from tempo import *
from tempo.scheduler import *
from datetime import datetime,timedelta,timezone,date
UTC=timezone.utc
def t(name,fn):
    t0=_time.time()
    try: r=fn(); print("OK ",name,"->",str(r)[:150],f"[{_time.time()-t0:.2f}s]")
    except Exception as e: print("EXC",name,"->",type(e).__name__,str(e).replace("\n"," | ")[:160],f"[{_time.time()-t0:.2f}s]")
# parse hostile
for s in ["FREQ=DAILY;BYMONTHDAY=0","FREQ=DAILY;BYHOUR=24","FREQ=DAILY;BYSECOND=60","freq=daily;count=3","RRULE:FREQ=DAILY;COUNT=0","FREQ=DAILY;INTERVAL=0","FREQ=DAILY;;","FREQ=DAILY;COUNT=2;UNTIL=20260101","FREQ=MONTHLY;BYDAY=+1MO,-1SU","FREQ=MONTHLY;BYDAY=0MO","FREQ=WEEKLY;BYDAY=2MO","FREQ=YEARLY;BYWEEKNO=54","FREQ=DAILY;BYSETPOS=1","FREQ=YEARLY;BYMONTH=13","FREQ=DAILY;UNTIL=20260230","FREQ=DAILY;BYDAY=","  FREQ=DAILY  ","FREQ=DAILY;BYMONTH=1,1,2","FREQ=MONTHLY;BYMONTHDAY=-31","FREQ=MONTHLY;BYMONTHDAY=32","FREQ=DAILY;INTERVAL=-1","FREQ=DAILY;COUNT=1.5","FREQ=DAILY;X-FOO=1", "FREQ=DAILY;BYHOUR=1,,2"]:
    t("parse "+s, lambda s=s: parse_rrule(s))
# semantics
t("never feb30", lambda: Recurrence("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30",datetime(2026,1,1),"UTC").take(3))
t("feb29 interval 4 from 2001", lambda: Recurrence("FREQ=YEARLY;INTERVAL=4",datetime(2001,2,28),"UTC").take(3))
t("feb29 yearly", lambda: [x.year for x in Recurrence("FREQ=YEARLY",datetime(2024,2,29),"UTC").take(4)])
t("monthly 31", lambda: [x.strftime('%m-%d') for x in Recurrence("FREQ=MONTHLY",datetime(2026,1,31),"UTC").take(5)])
t("rfc dtstart non-matching", lambda: [str(x) for x in Recurrence("FREQ=WEEKLY;BYDAY=MO;COUNT=2",datetime(2026,11,17,9),"UTC")])
t("until before dtstart", lambda: Recurrence("FREQ=DAILY;UNTIL=20200101T000000Z",datetime(2026,11,17,9),"UTC").take(5))
t("until utc aware zone", lambda: [str(x) for x in Recurrence("FREQ=DAILY;UNTIL=20261119T140000Z",datetime(2026,11,17,9),"America/New_York")])
t("until date", lambda: len(Recurrence("FREQ=DAILY;UNTIL=20261119",datetime(2026,11,17,9),"America/New_York").take(9)))
t("until utc floating", lambda: Recurrence("FREQ=DAILY;UNTIL=20261119T140000Z",datetime(2026,11,17,9)).take(2))
t("hourly across gap", lambda: [x.strftime('%H:%M%z') for x in Recurrence("FREQ=HOURLY;COUNT=5",datetime(2026,3,8,0,30),"America/New_York")])
t("minutely across gap", lambda: [x.astimezone(UTC).strftime('%H:%M') for x in Recurrence("FREQ=MINUTELY;INTERVAL=20;COUNT=9",datetime(2026,3,8,1,0),"America/New_York")])
t("gap skip", lambda: [str(x) for x in Recurrence("FREQ=DAILY;COUNT=3",datetime(2026,3,7,2,30),"America/New_York",gap="skip")])
t("exdate naive", lambda: [str(x.date()) for x in Recurrence("FREQ=DAILY;COUNT=4",datetime(2026,3,6,9),"America/New_York",exdates=[datetime(2026,3,7,9)])])
t("rdate dup", lambda: len(Recurrence("FREQ=DAILY;COUNT=3",datetime(2026,3,6,9),"UTC",rdates=[datetime(2026,3,7,9,tzinfo=UTC),datetime(2026,3,20,9,tzinfo=UTC)]).take(10)))
t("dtstart date obj", lambda: Recurrence("FREQ=DAILY;COUNT=2",date(2026,1,1)).take(2))
t("bad tz", lambda: Recurrence("FREQ=DAILY",datetime(2026,1,1),"Mars/Base"))
t("between empty", lambda: Recurrence("FREQ=DAILY",datetime(2026,1,1),"UTC").between(datetime(2026,2,1,tzinfo=UTC),datetime(2026,1,1,tzinfo=UTC)))
t("secondly sparse", lambda: Recurrence("FREQ=SECONDLY;BYSECOND=5,50;COUNT=4",datetime(2026,1,1),"UTC").take(4))
t("far future", lambda: Recurrence("FREQ=YEARLY;INTERVAL=1000",datetime(2026,1,1),"UTC").take(12)[-1])
t("count method inf", lambda: Recurrence("FREQ=DAILY",datetime(2026,1,1),"UTC").count(limit=100))
t("roundtrip", lambda: parse_rrule("FREQ=MONTHLY;BYDAY=2TU,-1FR,MO;INTERVAL=2;WKST=SU;BYHOUR=3").to_string())
# cron hostile
for e in ["* * * *","60 * * * *","* 24 * * *","* * 0 * *","* * * 13 *","* * * * 8","*/0 * * * *","5-1 * * * *","@weird","a b c d e","1,,2 * * * *","* * L-31 * *","0 0 31 2 *","0 0 30 2 *","0 0 29 2 1","@DAILY","0 0 * JAN-MAR MON-FRI","0 0 * * 5-7","0 0 * * 7#1","0 0 * * FRIL","0 0 ? * *","\t0  0 * * *"]:
    t("cron "+e, lambda e=e: Cron(e).next(datetime(2026,11,16,tzinfo=UTC)))
t("cron secs", lambda: Cron("* * * * *").next(datetime(2026,11,16,10,0,30,500,tzinfo=UTC)))
t("cron prev secs", lambda: Cron("* * * * *").prev(datetime(2026,11,16,10,0,30,500,tzinfo=UTC)))
t("cron prev exact", lambda: Cron("* * * * *").prev(datetime(2026,11,16,10,0,0,tzinfo=UTC)))
t("cron next exact", lambda: Cron("* * * * *").next(datetime(2026,11,16,10,0,0,tzinfo=UTC)))
t("cron naive input", lambda: Cron("0 9 * * *","Asia/Tokyo").next(datetime(2026,11,16,10)))
t("cron between", lambda: len(Cron("*/5 * * * *").between(datetime(2026,11,16,tzinfo=UTC),datetime(2026,11,16,1,tzinfo=UTC))))
t("cron 100k", lambda: len(Cron("* * * * *").take(datetime(2026,1,1,tzinfo=UTC),20000)))
t("cron lord howe", lambda: [str(x) for x in Cron("30 2 * * *","Australia/Lord_Howe").take(datetime(2026,10,3,tzinfo=UTC),3)])
# scheduler hostile
A=Attendee("a","UTC"); B=Attendee("b","Asia/Kolkata")
t("naive window", lambda: find_slots([A],datetime(2026,1,1),datetime(2026,1,2),timedelta(minutes=30)))
t("dur>window", lambda: find_slots([A],datetime(2026,1,5,tzinfo=UTC),datetime(2026,1,5,9,15,tzinfo=UTC),timedelta(hours=1)))
t("dup names", lambda: find_slots([A,A],datetime(2026,1,5,tzinfo=UTC),datetime(2026,1,6,tzinfo=UTC),timedelta(hours=1)))
t("kolkata", lambda: [s.start.isoformat() for s in find_slots([A,B],datetime(2026,1,5,tzinfo=UTC),datetime(2026,1,6,tzinfo=UTC),timedelta(hours=1))])
t("empty list", lambda: find_slots([],datetime(2026,1,5,tzinfo=UTC),datetime(2026,1,6,tzinfo=UTC),timedelta(hours=1)))
t("window huge", lambda: len(find_slots([A,B],datetime(2026,1,5,tzinfo=UTC),datetime(2027,1,6,tzinfo=UTC),timedelta(hours=1),limit=3)))
for h in ["Mon-Fri","Mon-Fri 17-9","Funday 9-5","Mon 25-26","Mon-Fri 9:00-17:00;","","Fri-Mon 9-17","Mon 9-12,13-17","Sat 22-24"]:
    t("hours "+h, lambda h=h: WorkHours.parse(h).describe())
