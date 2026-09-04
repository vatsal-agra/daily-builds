"""Core order/trade data types shared by the book, engine, and journal.

Kept deliberately dependency-free (stdlib `dataclasses` + `enum` only) so
they serialize trivially to/from the JSON-Lines journal format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(str, Enum):
    # Good-Till-Cancel: rests on the book until filled or cancelled.
    GTC = "GTC"
    # Immediate-Or-Cancel: fill whatever is immediately available, cancel
    # (do not rest) the remainder.
    IOC = "IOC"
    # Fill-Or-Kill: fill the *entire* quantity immediately, atomically, or
    # do nothing at all (reject with zero effect on the book).
    FOK = "FOK"


class OrderStatus(str, Enum):
    NEW = "NEW"
    OPEN = "OPEN"  # resting on the book with remaining_qty > 0
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class MatchbookError(Exception):
    """Base class for all Matchbook-raised errors."""


class ValidationError(MatchbookError):
    """A malformed order was rejected before it ever reached a book."""


@dataclass
class Order:
    order_id: int
    symbol: str
    side: Side
    order_type: OrderType
    qty: int
    price: float | None = None  # None only valid for MARKET orders
    tif: TimeInForce = TimeInForce.GTC
    agent_id: str = ""
    seq: int = 0  # monotonic arrival sequence number -> time priority
    remaining_qty: int = field(init=False)
    status: OrderStatus = field(default=OrderStatus.NEW, init=False)

    def __post_init__(self) -> None:
        if self.order_type == OrderType.MARKET:
            # Market orders have no resting price; force IOC-like semantics
            # unless the caller explicitly asked for FOK.
            self.price = None
            if self.tif == TimeInForce.GTC:
                self.tif = TimeInForce.IOC
        elif self.price is None:
            raise ValidationError(f"LIMIT order {self.order_id} requires a price")
        if self.qty <= 0:
            raise ValidationError(f"order {self.order_id} qty must be positive, got {self.qty}")
        if self.price is not None and self.price <= 0:
            raise ValidationError(f"order {self.order_id} price must be positive, got {self.price}")
        self.remaining_qty = self.qty

    @property
    def is_resting(self) -> bool:
        return self.status == OrderStatus.OPEN and self.remaining_qty > 0

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "qty": self.qty,
            "price": self.price,
            "tif": self.tif.value,
            "agent_id": self.agent_id,
            "seq": self.seq,
            "remaining_qty": self.remaining_qty,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Order":
        o = cls(
            order_id=d["order_id"],
            symbol=d["symbol"],
            side=Side(d["side"]),
            order_type=OrderType(d["order_type"]),
            qty=d["qty"],
            price=d["price"],
            tif=TimeInForce(d["tif"]),
            agent_id=d.get("agent_id", ""),
            seq=d.get("seq", 0),
        )
        o.remaining_qty = d.get("remaining_qty", o.qty)
        o.status = OrderStatus(d.get("status", o.status.value))
        return o


@dataclass(frozen=True)
class Trade:
    trade_id: int
    symbol: str
    price: float
    qty: int
    buy_order_id: int
    sell_order_id: int
    buy_agent: str
    sell_agent: str
    aggressor_side: Side
    seq: int  # sequence number at which the trade occurred

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "price": self.price,
            "qty": self.qty,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_agent": self.buy_agent,
            "sell_agent": self.sell_agent,
            "aggressor_side": self.aggressor_side.value,
            "seq": self.seq,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        return cls(
            trade_id=d["trade_id"],
            symbol=d["symbol"],
            price=d["price"],
            qty=d["qty"],
            buy_order_id=d["buy_order_id"],
            sell_order_id=d["sell_order_id"],
            buy_agent=d["buy_agent"],
            sell_agent=d["sell_agent"],
            aggressor_side=Side(d["aggressor_side"]),
            seq=d["seq"],
        )
