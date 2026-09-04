import unittest

from matchbook.order import Order, OrderType, Side, TimeInForce, ValidationError


class TestOrder(unittest.TestCase):
    def test_limit_requires_price(self):
        with self.assertRaises(ValidationError):
            Order(1, "X", Side.BUY, OrderType.LIMIT, 10, price=None)

    def test_market_forces_price_none(self):
        o = Order(1, "X", Side.BUY, OrderType.MARKET, 10, price=55.0)
        self.assertIsNone(o.price)

    def test_market_defaults_to_ioc(self):
        o = Order(1, "X", Side.BUY, OrderType.MARKET, 10)
        self.assertEqual(o.tif, TimeInForce.IOC)

    def test_market_can_be_fok(self):
        o = Order(1, "X", Side.BUY, OrderType.MARKET, 10, tif=TimeInForce.FOK)
        self.assertEqual(o.tif, TimeInForce.FOK)

    def test_nonpositive_qty_rejected(self):
        with self.assertRaises(ValidationError):
            Order(1, "X", Side.BUY, OrderType.LIMIT, 0, price=10.0)
        with self.assertRaises(ValidationError):
            Order(1, "X", Side.BUY, OrderType.LIMIT, -5, price=10.0)

    def test_nonpositive_price_rejected(self):
        with self.assertRaises(ValidationError):
            Order(1, "X", Side.BUY, OrderType.LIMIT, 5, price=0)
        with self.assertRaises(ValidationError):
            Order(1, "X", Side.BUY, OrderType.LIMIT, 5, price=-1.0)

    def test_remaining_qty_initialized(self):
        o = Order(1, "X", Side.BUY, OrderType.LIMIT, 42, price=1.0)
        self.assertEqual(o.remaining_qty, 42)

    def test_round_trip_dict(self):
        o = Order(7, "ACME", Side.SELL, OrderType.LIMIT, 30, price=12.5, agent_id="bob", seq=3)
        o.remaining_qty = 10
        d = o.to_dict()
        o2 = Order.from_dict(d)
        self.assertEqual(o2.order_id, 7)
        self.assertEqual(o2.remaining_qty, 10)
        self.assertEqual(o2.agent_id, "bob")
        self.assertEqual(o2.seq, 3)

    def test_opposite_side(self):
        self.assertEqual(Side.BUY.opposite, Side.SELL)
        self.assertEqual(Side.SELL.opposite, Side.BUY)


if __name__ == "__main__":
    unittest.main()
