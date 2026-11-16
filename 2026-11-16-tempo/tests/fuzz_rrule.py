import sys,random,signal
class TO(Exception):pass
def _h(*a): raise TO()
signal.signal(signal.SIGALRM,_h)
sys.path.insert(0,'.')
import os
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))
from tempo.rrule import parse_rrule, expand_wall
from tempo.errors import TempoError
from dateutil.rrule import rrulestr
from datetime import datetime
from itertools import islice
DAYS=["MO","TU","WE","TH","FR","SA","SU"]
def rnd_rule():
    f=random.choice(["YEARLY","MONTHLY","WEEKLY","DAILY","HOURLY","MINUTELY"])
    p=["FREQ="+f]
    if random.random()<.5: p.append(f"INTERVAL={random.randint(1,5)}")
    if random.random()<.3: p.append("WKST="+random.choice(DAYS))
    def pick(lo,hi,k,neg=False):
        vals=random.sample(range(lo,hi+1),k)
        if neg: vals=[v if random.random()<.7 else -v for v in vals]
        return ",".join(map(str,vals))
    if random.random()<.3: p.append("BYMONTH="+pick(1,12,random.randint(1,3)))
    if f=="YEARLY" and random.random()<.15: p.append("BYWEEKNO="+pick(1,53,random.randint(1,2),True))
    if f in("YEARLY","HOURLY","MINUTELY") and random.random()<.15: p.append("BYYEARDAY="+pick(1,366,random.randint(1,3),True))
    if f!="WEEKLY" and random.random()<.3: p.append("BYMONTHDAY="+pick(1,31,random.randint(1,3),True))
    if random.random()<.45:
        ords = f in("MONTHLY","YEARLY") and not any(x.startswith("BYWEEKNO") for x in p) and random.random()<.5
        ds=[]
        for d in random.sample(DAYS,random.randint(1,3)):
            ds.append((str(random.choice([1,2,3,-1,-2])) if ords else "")+d)
        p.append("BYDAY="+",".join(ds))
    if random.random()<.4 and f in("YEARLY","MONTHLY","WEEKLY","DAILY"): p.append("BYHOUR="+pick(0,23,random.randint(1,2)))
    if random.random()<.3 and f!="MINUTELY": p.append("BYMINUTE="+pick(0,59,random.randint(1,2)))
    if random.random()<.15: p.append("BYSECOND="+pick(0,59,random.randint(1,2)))
    if len(p)>1 and random.random()<.25 and f in("YEARLY","MONTHLY","WEEKLY","DAILY"): p.append("BYSETPOS="+pick(1,4,1,True))
    if random.random()<.5: p.append(f"COUNT={random.randint(1,30)}")
    elif random.random()<.5: p.append("UNTIL=%04d%02d%02dT000000"%(random.randint(2026,2032),random.randint(1,12),random.randint(1,28)))
    return ";".join(p)
def run(seed, count, verbose=False):
    random.seed(seed)
    bad=0;n=0;skipped=0
    for i in range(count):
        rs=rnd_rule()
        dt=datetime(random.randint(2020,2028),random.randint(1,12),random.randint(1,28),random.randint(0,23),random.randint(0,59),random.randint(0,59))
        try: r=parse_rrule(rs)
        except TempoError as e:
            skipped+=1; continue
        cap=40
        if r.freq=='WEEKLY' and r.bysetpos: skipped+=1; continue
        signal.alarm(3)
        try:
            ref=list(islice(rrulestr(rs,dtstart=dt),cap))
            mine=list(islice(expand_wall(r,dt),cap))
        except (Exception,TO) as e:
            skipped+=1; signal.alarm(0); continue
        signal.alarm(0)
        n+=1
        if ref!=mine:
            bad+=1
            if verbose and bad<=8:
                print("MISMATCH",rs,dt); print("  ref ",[x.isoformat() for x in ref[:6]], len(ref)); print("  mine",[x.isoformat() for x in mine[:6]], len(mine))
    return n, bad

if __name__=='__main__':
    print('compared %d, mismatches %d' % run(int(sys.argv[1]) if len(sys.argv)>1 else 1, int(sys.argv[2]) if len(sys.argv)>2 else 300, True))
