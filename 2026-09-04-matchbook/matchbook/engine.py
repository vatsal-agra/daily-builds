"""Exchange: the multi-symbol router that ties together order books, the
pre-trade risk gate, and the write-ahead journal.

Every order/cancel/modify command is journaled *before* it is applied to any
`OrderBook` -- see `journal.py` for why that ordering is the whole point.
`Exchange.replay()` reconstructs an Exchange purely from a journal file,
which is both the crash-recovery mechanism and an independent correctness
oracle: if replaying a session doesn't reproduce byte-identical final state,
something is nondeterministic (a bug), because nothing in this engine is
allowed to depend on wall-clock time, hash-randomized iteration order, or
any other non-reproducible input.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .book import OrderBook
from .journal import Journal
from .order import Order, OrderStatus, OrderType, Side, TimeInForce, Trade
from .risk import RiskEngine, RiskLimits


@dataclass
class ExchangeConfig:
    symbols: list[str]
    self_trade_prevention: bool = True
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


class Exchange:
    def __init__(
        self,
        symbols: list[str],
        journal_path: str | None = None,
        risk_limits: RiskLimits | None = None,
        self_trade_prevention: bool = True,
        truncate_journal: bool = True,
    ):
        self.symbols = list(symbols)
        self.self_trade_prevention = self_trade_prevention
        self.books: dict[str, OrderBook] = {
            s: OrderBook(s, self_trade_prevention=self_trade_prevention) for s in self.symbols
        }
        self.risk = RiskEngine(risk_limits)
        self.journal: Journal | None = (
            Journal(journal_path, truncate=truncate_journal) if journal_path else None
        )

        self._next_order_id = 1
        self._order_seq = 0

        self.all_orders: dict[int, Order] = {}
        self.trade_tape: list[Trade] = []
        self.last_price: dict[str, float] = {}
        self.positions: dict[tuple[str, str], int] = {}   # (agent_id, symbol) -> shares
        self.cash: dict[str, float] = {}                  # agent_id -> realized cash flow
        self.rejections: list[dict] = []
        self.stp_events: list[dict] = []

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        if self.journal is not None:
            self.journal.close()

    def _log(self, event: dict) -> None:
        if self.journal is not None:
            self.journal.append(event)

    def book(self, symbol: str) -> OrderBook:
        return self.books[symbol]

    @property
    def order_seq_counter(self) -> int:
        """The next order-arrival sequence number that will be assigned.
        Every trade/order with `.seq < order_seq_counter` has already
        happened; this is the correct watermark for "as of now" filtering
        (ticks and seq numbers are on different scales -- many orders are
        submitted per simulated tick -- so a tick index alone can't be
        compared against a `seq` value)."""
        return self._order_seq

    # ------------------------------------------------------------------ #
    # Order entry API
    # ------------------------------------------------------------------ #
    def submit_order(
        self,
        symbol: str,
        side: Side | str,
        order_type: OrderType | str,
        qty: int,
        price: float | None = None,
        tif: TimeInForce | str = TimeInForce.GTC,
        agent_id: str = "",
    ) -> Order:
        if symbol not in self.books:
            raise KeyError(
                f"unknown symbol {symbol!r}; this exchange only lists {sorted(self.books)}"
            )
        order = Order(
            order_id=self._next_order_id,
            symbol=symbol,
            side=Side(side),
            order_type=OrderType(order_type),
            qty=qty,
            price=price,
            tif=TimeInForce(tif),
            agent_id=agent_id,
            seq=self._order_seq,
        )
        self._next_order_id += 1
        self._order_seq += 1

        current_position = self.positions.get((agent_id, symbol), 0)
        last_price = self.last_price.get(symbol)
        ok, reason = self.risk.check(order, current_position, last_price)
        if not ok:
            order.status = OrderStatus.REJECTED
            event = order.to_dict()
            event["cmd"] = "SUBMIT"
            event["rejected_pretrade"] = True
            event["reason"] = reason
            self._log(event)
            self.all_orders[order.order_id] = order
            self.rejections.append(
                {"order_id": order.order_id, "agent_id": agent_id, "symbol": symbol, "reason": reason}
            )
            return order

        event = order.to_dict()
        event["cmd"] = "SUBMIT"
        self._log(event)
        self._apply_submit(order)
        return order

    def cancel_order(self, order_id: int) -> bool:
        self._log({"cmd": "CANCEL", "order_id": order_id})
        return self._apply_cancel(order_id)

    def modify_order(self, order_id: int, new_price: float | None = None, new_qty: int | None = None) -> Order | None:
        self._log({"cmd": "MODIFY", "order_id": order_id, "new_price": new_price, "new_qty": new_qty})
        return self._apply_modify(order_id, new_price, new_qty)

    # ------------------------------------------------------------------ #
    # Internal apply (shared by live order entry and journal replay)
    # ------------------------------------------------------------------ #
    def _apply_submit(self, order: Order) -> list[Trade]:
        book = self.books[order.symbol]
        trades = book.submit(order)
        for cancelled_id in book.stp_cancels:
            self.stp_events.append({"order_id": cancelled_id, "cancelled_by": order.order_id})
        for t in trades:
            self._apply_trade(t)
        self.all_orders[order.order_id] = order
        return trades

    def _apply_trade(self, t: Trade) -> None:
        self.trade_tape.append(t)
        self.last_price[t.symbol] = t.price
        self.positions[(t.buy_agent, t.symbol)] = self.positions.get((t.buy_agent, t.symbol), 0) + t.qty
        self.positions[(t.sell_agent, t.symbol)] = self.positions.get((t.sell_agent, t.symbol), 0) - t.qty
        self.cash[t.buy_agent] = self.cash.get(t.buy_agent, 0.0) - t.price * t.qty
        self.cash[t.sell_agent] = self.cash.get(t.sell_agent, 0.0) + t.price * t.qty

    def _apply_cancel(self, order_id: int) -> bool:
        order = self.all_orders.get(order_id)
        if order is None or not order.is_resting:
            return False
        return self.books[order.symbol].cancel(order_id)

    def _apply_modify(self, order_id: int, new_price: float | None, new_qty: int | None) -> Order | None:
        order = self.all_orders.get(order_id)
        if order is None or not order.is_resting:
            return None
        replacement = self.books[order.symbol].modify(order_id, new_price, new_qty)
        if replacement is not None:
            self.all_orders[order_id] = replacement
        return replacement

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def mark_to_market_pnl(self, agent_id: str) -> float:
        total = self.cash.get(agent_id, 0.0)
        for symbol in self.symbols:
            pos = self.positions.get((agent_id, symbol), 0)
            price = self.last_price.get(symbol)
            if pos and price is not None:
                total += pos * price
        return total

    def summary(self) -> dict:
        agents = sorted({a for a, _ in self.positions.keys()} | set(self.cash.keys()))
        return {
            "trade_count": len(self.trade_tape),
            "last_price": dict(self.last_price),
            "rejections": len(self.rejections),
            "stp_cancels": len(self.stp_events),
            "agents": {
                a: {
                    "cash": round(self.cash.get(a, 0.0), 2),
                    "positions": {
                        s: self.positions.get((a, s), 0) for s in self.symbols if self.positions.get((a, s), 0)
                    },
                    "pnl": round(self.mark_to_market_pnl(a), 2),
                }
                for a in agents
            },
        }

    # ------------------------------------------------------------------ #
    # Crash recovery: rebuild an Exchange purely from its journal.
    # ------------------------------------------------------------------ #
    @classmethod
    def replay(
        cls,
        journal_path: str,
        symbols: list[str],
        risk_limits: RiskLimits | None = None,
        self_trade_prevention: bool = True,
    ) -> "Exchange":
        events = Journal.read_all(journal_path)
        ex = cls(
            symbols=symbols,
            journal_path=None,
            risk_limits=risk_limits,
            self_trade_prevention=self_trade_prevention,
        )
        for ev in events:
            cmd = ev.get("cmd")
            if cmd == "SUBMIT":
                order = Order.from_dict(ev)
                ex._next_order_id = max(ex._next_order_id, order.order_id + 1)
                ex._order_seq = max(ex._order_seq, order.seq + 1)
                if ev.get("rejected_pretrade"):
                    ex.all_orders[order.order_id] = order
                    ex.rejections.append(
                        {
                            "order_id": order.order_id,
                            "agent_id": order.agent_id,
                            "symbol": order.symbol,
                            "reason": ev.get("reason"),
                        }
                    )
                else:
                    ex._apply_submit(order)
            elif cmd == "CANCEL":
                ex._apply_cancel(ev["order_id"])
            elif cmd == "MODIFY":
                ex._apply_modify(ev["order_id"], ev.get("new_price"), ev.get("new_qty"))
            # unknown/future command types are ignored rather than fatal,
            # so a journal never becomes unreplayable because of a minor
            # version skew in optional audit-only fields.
        return ex

    def state_fingerprint(self) -> dict:
        """A compact, order-independent snapshot of everything that matters
        for "is this the same state as that other Exchange" -- used by the
        crash-recovery test to compare live vs. replayed state without
        depending on object identity or dict ordering."""
        book_states = {}
        for symbol, book in self.books.items():
            book_states[symbol] = {
                "bids": sorted(
                    (
                        (price, tuple((o.order_id, o.remaining_qty) for o in level.orders))
                        for price, level in book.bid_levels.items()
                        if level.orders
                    )
                ),
                "asks": sorted(
                    (
                        (price, tuple((o.order_id, o.remaining_qty) for o in level.orders))
                        for price, level in book.ask_levels.items()
                        if level.orders
                    )
                ),
            }
        return {
            "books": book_states,
            "trade_tape": [t.to_dict() for t in self.trade_tape],
            "positions": dict(sorted(self.positions.items())),
            "cash": {k: round(v, 6) for k, v in sorted(self.cash.items())},
            "last_price": dict(sorted(self.last_price.items())),
            "next_order_id": self._next_order_id,
            "order_seq": self._order_seq,
        }
