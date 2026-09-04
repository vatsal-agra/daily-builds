import unittest

from matchbook.order import Order, OrderType, Side
from matchbook.risk import RiskEngine, RiskLimits


def mk(oid, side, qty, price, agent="a"):
    return Order(oid, "X", side, OrderType.LIMIT, qty, price=price, agent_id=agent)


class TestRiskEngine(unittest.TestCase):
    def test_no_limits_allows_everything(self):
        r = RiskEngine(RiskLimits(position_limit=None, fat_finger_pct=None, max_order_qty=None))
        ok, reason = r.check(mk(1, Side.BUY, 1_000_000, 1_000_000.0), current_position=0, last_price=None)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_position_limit_boundary_is_inclusive(self):
        r = RiskEngine(RiskLimits(position_limit=100, fat_finger_pct=None))
        ok, _ = r.check(mk(1, Side.BUY, 100, 10.0), current_position=0, last_price=None)
        self.assertTrue(ok)  # exactly at the limit
        ok, reason = r.check(mk(2, Side.BUY, 101, 10.0), current_position=0, last_price=None)
        self.assertFalse(ok)
        self.assertIn("exceeding limit", reason)

    def test_position_limit_considers_existing_position(self):
        r = RiskEngine(RiskLimits(position_limit=100, fat_finger_pct=None))
        ok, _ = r.check(mk(1, Side.BUY, 10, 10.0), current_position=95, last_price=None)
        self.assertFalse(ok)  # 95 + 10 = 105 > 100

    def test_sell_side_reduces_position_toward_short_limit(self):
        r = RiskEngine(RiskLimits(position_limit=50, fat_finger_pct=None))
        ok, _ = r.check(mk(1, Side.SELL, 60, 10.0), current_position=0, last_price=None)
        self.assertFalse(ok)  # would go to -60, beyond the 50 limit

    def test_fat_finger_pct_boundary(self):
        r = RiskEngine(RiskLimits(position_limit=None, fat_finger_pct=0.10))
        ok, _ = r.check(mk(1, Side.BUY, 1, 110.0), current_position=0, last_price=100.0)
        self.assertTrue(ok)  # exactly 10% away
        ok, reason = r.check(mk(2, Side.BUY, 1, 111.0), current_position=0, last_price=100.0)
        self.assertFalse(ok)
        self.assertIn("fat-finger", reason)

    def test_market_orders_are_never_fat_fingered(self):
        r = RiskEngine(RiskLimits(fat_finger_pct=0.01))
        order = Order(1, "X", Side.BUY, OrderType.MARKET, 10)
        ok, _ = r.check(order, current_position=0, last_price=100.0)
        self.assertTrue(ok)

    def test_max_order_qty(self):
        r = RiskEngine(RiskLimits(max_order_qty=50, position_limit=None, fat_finger_pct=None))
        ok, _ = r.check(mk(1, Side.BUY, 50, 10.0), current_position=0, last_price=None)
        self.assertTrue(ok)
        ok, reason = r.check(mk(2, Side.BUY, 51, 10.0), current_position=0, last_price=None)
        self.assertFalse(ok)
        self.assertIn("max_order_qty", reason)


if __name__ == "__main__":
    unittest.main()
