import unittest

from bellman.nn import MLP
from bellman.autodiff import Value


class TestMLP(unittest.TestCase):
    def test_forward_shape(self):
        net = MLP([4, 8, 2], seed=0)
        out = net([Value(0.1), Value(-0.2), Value(0.3), Value(0.0)])
        self.assertEqual(len(out), 2)
        for v in out:
            self.assertIsInstance(v, Value)

    def test_parameter_count(self):
        net = MLP([4, 8, 2], seed=0)
        # layer1: 4*8 weights + 8 biases; layer2: 8*2 weights + 2 biases
        expected = (4 * 8 + 8) + (8 * 2 + 2)
        self.assertEqual(len(net.parameters()), expected)

    def test_zero_grad_clears_all_params(self):
        net = MLP([2, 3, 1], seed=1)
        out = net([Value(1.0), Value(-1.0)])
        out[0].backward()
        self.assertTrue(any(p.grad != 0.0 for p in net.parameters()))
        net.zero_grad()
        self.assertTrue(all(p.grad == 0.0 for p in net.parameters()))

    def test_relu_applied_to_hidden_not_output(self):
        # Force a large negative bias on the output layer and confirm the raw
        # (non-relu'd) negative value survives -- relu must not be applied
        # after the final layer.
        net = MLP([1, 1, 1], seed=2)
        net.layers[-1].b[0].data = -5.0
        net.layers[-1].W[0][0].data = 0.0
        out = net([Value(1.0)])
        self.assertLess(out[0].data, 0.0)

    def test_deterministic_given_seed(self):
        net_a = MLP([3, 4, 2], seed=42)
        net_b = MLP([3, 4, 2], seed=42)
        a_weights = [w.data for layer in net_a.layers for row in layer.W for w in row]
        b_weights = [w.data for layer in net_b.layers for row in layer.W for w in row]
        self.assertEqual(a_weights, b_weights)

    def test_state_dict_roundtrip_shape(self):
        net = MLP([4, 8, 2], seed=0)
        sd = net.state_dict()
        self.assertEqual(sd["sizes"], [4, 8, 2])
        self.assertEqual(len(sd["layers"]), 2)
        self.assertEqual(len(sd["layers"][0]["W"]), 8)
        self.assertEqual(len(sd["layers"][0]["W"][0]), 4)
        self.assertEqual(len(sd["layers"][1]["W"]), 2)


if __name__ == "__main__":
    unittest.main()
