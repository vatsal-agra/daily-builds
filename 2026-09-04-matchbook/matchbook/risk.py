"""A pre-trade risk gate every order passes through before it reaches a book.

Three independent checks, each individually toggleable:

  - **Position limits**: reject an order whose worst-case (fully filled)
    resulting position for that agent+symbol would exceed a configured
    absolute share limit.
  - **Self-trade prevention** is enforced inside `OrderBook` itself (it needs
    to see the resting queue), but this module still records the setting so
    `Exchange` can report it consistently.
  - **Fat-finger collar**: reject a LIMIT order priced further than a
    configured percentage away from the symbol's last traded price. (No
    check is possible before the very first trade -- there is nothing to
    collar against yet.)

Every rejection is returned with a human-readable reason so the simulator
and the journal can record *why*, not just *that*, an order was refused.
"""
from __future__ import annotations

from dataclasses import dataclass

from .order import Order, OrderType


@dataclass
class RiskLimits:
    position_limit: int | None = None       # max abs(shares) per agent per symbol
    fat_finger_pct: float | None = 0.25      # max fractional distance from last price
    max_order_qty: int | None = None         # reject single orders larger than this


class RiskViolation(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def check(
        self,
        order: Order,
        current_position: int,
        last_price: float | None,
    ) -> tuple[bool, str | None]:
        """Returns (ok, reason). `current_position` is the agent's existing
        signed position in `order.symbol` *before* this order. `last_price`
        is the symbol's most recent trade price, or None if it has never
        traded."""
        lim = self.limits

        if lim.max_order_qty is not None and order.qty > lim.max_order_qty:
            return False, (
                f"order qty {order.qty} exceeds max_order_qty {lim.max_order_qty}"
            )

        if lim.position_limit is not None:
            delta = order.qty if order.side.value == "BUY" else -order.qty
            worst_case = current_position + delta
            if abs(worst_case) > lim.position_limit:
                return False, (
                    f"would move {order.agent_id}'s {order.symbol} position to "
                    f"{worst_case}, exceeding limit {lim.position_limit}"
                )

        if (
            lim.fat_finger_pct is not None
            and order.order_type == OrderType.LIMIT
            and last_price is not None
        ):
            distance = abs(order.price - last_price) / last_price
            if distance > lim.fat_finger_pct:
                return False, (
                    f"price {order.price} is {distance:.1%} from last trade "
                    f"{last_price}, exceeding fat-finger collar {lim.fat_finger_pct:.0%}"
                )

        return True, None
