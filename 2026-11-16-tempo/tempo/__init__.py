"""Tempo — a from-scratch recurrence engine (RRULE, cron, ICS, English) and meeting finder."""
from .errors import TempoError, RRuleError, CronError, ICSError, NLError
from .rrule import Rule, parse_rrule, expand_wall
from .recur import Recurrence
from .cron import Cron
from .scheduler import Attendee, WorkHours, find_slots, Interval
from .ics import parse_ics, write_ics, Event, Calendar
from .nlp import english_to_rrule, rrule_to_english

__all__ = [n for n in dir() if not n.startswith("_")]
__version__ = "1.0.0"
