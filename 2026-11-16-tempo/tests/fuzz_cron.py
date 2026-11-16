import sys,random
sys.path.insert(0,'.')
import os
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))
from tempo.cron import Cron
from croniter import croniter
from datetime import datetime, timezone
def field(lo,hi,names=None,nostar=False):
    r=random.random()
    if nostar and .3<=r<.45: r=.5
    if r<.3: return "*"
    if r<.45: return f"*/{random.randint(2,max(2,(hi-lo)//2))}"
    if r<.6:
        a=random.randint(lo,hi-1); b=random.randint(a+1,hi); return f"{a}-{b}"
    if r<.7:
        a=random.randint(lo,hi-1); b=random.randint(a+1,hi); return f"{a}-{b}/{random.randint(1,4)}"
    return ",".join(str(random.randint(lo,hi)) for _ in range(random.randint(1,3)))
def run(seed, count, verbose=False):
    random.seed(seed)
    bad=n=0
    for i in range(count):
        e=" ".join([field(0,59),field(0,23),field(1,28,nostar=True),field(1,12),field(0,6,nostar=True)])
        start=datetime(random.randint(2020,2030),random.randint(1,12),random.randint(1,28),random.randint(0,23),random.randint(0,59),tzinfo=timezone.utc)
        try: it=croniter(e,start.replace(tzinfo=None)); ref=[it.get_next(datetime) for _ in range(12)]
        except Exception as ex: continue
        mine=[x.replace(tzinfo=None) for x in Cron(e).take(start,12)]
        n+=1
        if ref!=mine:
            bad+=1
            if verbose and bad<6: print("MISMATCH",e,start,"\n ref ",ref[:4],"\n mine",mine[:4])
        # prev check
        pm=Cron(e).prev(start).replace(tzinfo=None)
        pr=croniter(e,start.replace(tzinfo=None)).get_prev(datetime)
        if pm!=pr:
            bad+=1
            if verbose and bad<6: print("PREV MISMATCH",e,start,pm,pr)
    return n, bad

if __name__=='__main__':
    print('compared %d, mismatches %d' % run(int(sys.argv[1]) if len(sys.argv)>1 else 1, int(sys.argv[2]) if len(sys.argv)>2 else 300, True))
