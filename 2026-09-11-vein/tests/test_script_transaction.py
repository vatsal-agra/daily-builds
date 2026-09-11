import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.core.script import Script, execute, ScriptError, OP_CHECKMULTISIG
from vein.core.transaction import (
    Transaction, TxIn, TxOut, NULL_TXID, NULL_INDEX, merkle_root, merkle_proof,
)
from vein.crypto.curve import derive_pubkey
from vein.crypto.ecdsa import generate_privkey
from vein.crypto.address import serialize_pubkey
from vein.crypto.hashes import hash160, double_sha256


def _keypair():
    priv = generate_privkey()
    pub = serialize_pubkey(derive_pubkey(priv))
    return priv, pub


class TestScript(unittest.TestCase):
    def test_p2pkh_serialize_roundtrip(self):
        pkh = os.urandom(20)
        s = Script.p2pkh_lock(pkh)
        self.assertTrue(s.is_p2pkh())
        raw = s.serialize()
        back = Script.deserialize(raw)
        self.assertEqual(back.ops, s.ops)
        self.assertTrue(back.is_p2pkh())

    def test_pushdata1_roundtrip(self):
        big = os.urandom(200)
        s = Script([big])
        back = Script.deserialize(s.serialize())
        self.assertEqual(back.ops, [big])

    def test_op_0_roundtrip(self):
        s = Script([b""])
        back = Script.deserialize(s.serialize())
        self.assertEqual(back.ops, [b""])

    def test_p2pkh_valid_spend(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        lock = Script.p2pkh_lock(pkh)

        class FakeChecker:
            def __call__(self, pubkey_bytes, sig):
                return pubkey_bytes == pub  # good-faith checker stand-in

        unlock = Script.p2pkh_unlock(b"\x30\x02\x01\x01\x01", pub)  # not a real sig; checker below ignores bytes
        self.assertTrue(execute(unlock, lock, lambda pk, sig: pk == pub))

    def test_p2pkh_wrong_pubkey_hash_fails(self):
        priv, pub = _keypair()
        wrong_pkh = os.urandom(20)
        lock = Script.p2pkh_lock(wrong_pkh)
        unlock = Script.p2pkh_unlock(b"sig", pub)
        with self.assertRaises(ScriptError):
            execute(unlock, lock, lambda pk, sig: True)  # EQUALVERIFY should fail first

    def test_checksig_false_leaves_falsy_stack(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        lock = Script.p2pkh_lock(pkh)
        unlock = Script.p2pkh_unlock(b"badsig", pub)
        self.assertFalse(execute(unlock, lock, lambda pk, sig: False))

    def test_stack_underflow_raises(self):
        s = Script([0x76])  # OP_DUP on empty stack
        with self.assertRaises(ScriptError):
            execute(Script([]), s, lambda pk, sig: True)

    def test_unknown_opcode_raises(self):
        s = Script([0xFF])
        with self.assertRaises(ScriptError):
            execute(Script([]), s, lambda pk, sig: True)

    def test_multisig_2_of_3(self):
        keys = [_keypair() for _ in range(3)]
        pubkeys = [pub for _, pub in keys]
        lock = Script.multisig_lock(2, pubkeys)
        # sign with keys 0 and 2 (order must match pubkey order for our simple algorithm)
        unlock = Script.multisig_unlock([b"sig0", b"sig2"])
        good_sigs = {b"sig0": pubkeys[0], b"sig2": pubkeys[2]}

        def checker(pk, sig):
            return good_sigs.get(sig) == pk

        self.assertTrue(execute(unlock, lock, checker))

    def test_multisig_insufficient_signatures_fails(self):
        keys = [_keypair() for _ in range(3)]
        pubkeys = [pub for _, pub in keys]
        lock = Script.multisig_lock(2, pubkeys)
        unlock = Script.multisig_unlock([b"sig0"])  # only 1 of the required 2
        self.assertFalse(execute(unlock, lock, lambda pk, sig: sig == b"sig0" and pk == pubkeys[0]))


class TestTransaction(unittest.TestCase):
    def test_serialize_roundtrip(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        tx = Transaction(
            inputs=[TxIn(os.urandom(32), 3, Script([b"sig", pub]))],
            outputs=[TxOut(12345, Script.p2pkh_lock(pkh)), TxOut(999, Script.p2pkh_lock(pkh))],
        )
        back = Transaction.deserialize(tx.serialize())
        self.assertEqual(back.txid(), tx.txid())
        self.assertEqual(len(back.inputs), 1)
        self.assertEqual(len(back.outputs), 2)

    def test_coinbase_detection(self):
        cb = Transaction(inputs=[TxIn(NULL_TXID, NULL_INDEX, Script([b"h"]))], outputs=[TxOut(1, Script([]))])
        self.assertTrue(cb.is_coinbase())
        normal = Transaction(inputs=[TxIn(os.urandom(32), 0, Script([]))], outputs=[TxOut(1, Script([]))])
        self.assertFalse(normal.is_coinbase())

    def test_sign_and_verify_spend(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        prevout = TxOut(5000, Script.p2pkh_lock(pkh))
        tx = Transaction(inputs=[TxIn(os.urandom(32), 0, Script([]))], outputs=[TxOut(4900, Script.p2pkh_lock(pkh))])
        tx.sign_input(0, priv, prevout.script_pubkey, pub)
        checker = tx.make_sig_checker(0, prevout.script_pubkey)
        self.assertTrue(execute(tx.inputs[0].script_sig, prevout.script_pubkey, checker))

    def test_tamper_after_signing_invalidates(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        prevout = TxOut(5000, Script.p2pkh_lock(pkh))
        tx = Transaction(inputs=[TxIn(os.urandom(32), 0, Script([]))], outputs=[TxOut(4900, Script.p2pkh_lock(pkh))])
        tx.sign_input(0, priv, prevout.script_pubkey, pub)
        tampered = Transaction.deserialize(tx.serialize())
        tampered.outputs[0].value += 1
        checker = tampered.make_sig_checker(0, prevout.script_pubkey)
        self.assertFalse(execute(tampered.inputs[0].script_sig, prevout.script_pubkey, checker))

    def test_signature_does_not_carry_to_different_tx(self):
        priv, pub = _keypair()
        pkh = hash160(pub)
        prevout = TxOut(5000, Script.p2pkh_lock(pkh))
        tx1 = Transaction(inputs=[TxIn(os.urandom(32), 0, Script([]))], outputs=[TxOut(4900, Script.p2pkh_lock(pkh))])
        tx1.sign_input(0, priv, prevout.script_pubkey, pub)

        tx2 = Transaction(inputs=[TxIn(tx1.inputs[0].prev_txid, 0, tx1.inputs[0].script_sig)],
                           outputs=[TxOut(1, Script.p2pkh_lock(pkh))])  # different outputs, reused scriptSig
        checker = tx2.make_sig_checker(0, prevout.script_pubkey)
        self.assertFalse(execute(tx2.inputs[0].script_sig, prevout.script_pubkey, checker))


class TestMerkle(unittest.TestCase):
    def test_single_leaf_is_its_own_root(self):
        leaf = os.urandom(32)
        self.assertEqual(merkle_root([leaf]), leaf)

    def test_two_leaves(self):
        a, b = os.urandom(32), os.urandom(32)
        self.assertEqual(merkle_root([a, b]), double_sha256(a + b))

    def test_three_leaves_duplicates_last(self):
        a, b, c = os.urandom(32), os.urandom(32), os.urandom(32)
        top_left = double_sha256(a + b)
        top_right = double_sha256(c + c)
        self.assertEqual(merkle_root([a, b, c]), double_sha256(top_left + top_right))

    def test_proofs_for_various_sizes(self):
        for n in [1, 2, 3, 4, 5, 7, 8, 13, 16]:
            leaves = [os.urandom(32) for _ in range(n)]
            root = merkle_root(leaves)
            for i in range(n):
                proof = merkle_proof(leaves, i)
                self.assertTrue(proof.verify(leaves[i], root), f"n={n} i={i}")

    def test_wrong_leaf_fails_proof(self):
        leaves = [os.urandom(32) for _ in range(6)]
        root = merkle_root(leaves)
        proof = merkle_proof(leaves, 2)
        self.assertFalse(proof.verify(os.urandom(32), root))

    def test_empty_tree(self):
        self.assertEqual(merkle_root([]), b"\x00" * 32)


if __name__ == "__main__":
    unittest.main()
