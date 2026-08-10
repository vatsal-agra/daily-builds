"""Order/Trade data model shared across the matching engine and simulator.

Prices are integer *ticks* (not floats) throughout the engine, exactly
like a real exchange — this sidesteps floating-point comparison bugs in
price-time priority and makes "does the book cross" a plain integer
comparison. Callers that want dollars can divide by TICKS_PER_UNIT.
"""
from dataclasses import dataclass, field
from enum import Enum
import itertools

TICKS_PER_UNIT = 100  # 1 unit (e.g. "$1.00") = 100 ticks (i.e. cents)

_id_counter = itertools.count(1)


def next_order_id():
    return next(_id_counter)


def reset_id_counter():
    """Only for test isolation — resets the global order-id sequence."""
    global _id_counter
    _id_counter = itertools.count(1)


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self):
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    IOC = "IOC"    # immediate-or-cancel: fill what you can now, cancel the rest
    FOK = "FOK"    # fill-or-kill: fill completely now, or do nothing at all


@dataclass
class Order:
    id: int
    side: Side
    otype: OrderType
    qty: int                 # remaining unfilled quantity
    price: int = None        # ticks; None for MARKET orders
    ts: int = 0               # simulated tick timestamp, used for time-priority
    owner: str = "?"          # agent name, for P&L attribution
    orig_qty: int = field(default=None)

    def __post_init__(self):
        if self.orig_qty is None:
            self.orig_qty = self.qty


@dataclass
class Trade:
    price: int
    qty: int
    ts: int
    aggressor_side: Side      # side of the order that crossed the book
    maker_order_id: int
    taker_order_id: int
    maker_owner: str
    taker_owner: str
