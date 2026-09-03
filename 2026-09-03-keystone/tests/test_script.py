import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import crypto, script


class TestP2PKH(unittest.TestCase):
    def test_valid_spend(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        pub_bytes = crypto.compress_pubkey(pub)
        pkh = crypto.hash160(pub_bytes)
        lock = script.p2pkh_lock(pkh)
        sighash = crypto.sha256(b"tx body")
        unlock = script.p2pkh_unlock(priv, sighash, pub_bytes)
        self.assertTrue(script.execute(unlock, lock, sighash))

    def test_wrong_key_rejected(self):
        priv = crypto.generate_private_key()
        pub = crypto.private_to_public(priv)
        pkh = crypto.hash160(crypto.compress_pubkey(pub))
        lock = script.p2pkh_lock(pkh)

        thief_priv = crypto.generate_private_key()
        thief_pub_bytes = crypto.compress_pubkey(crypto.private_to_public(thief_priv))
        sighash = crypto.sha256(b"tx body")
        unlock = script.p2pkh_unlock(thief_priv, sighash, thief_pub_bytes)
        self.assertFalse(script.execute(unlock, lock, sighash))

    def test_tampered_sighash_rejected(self):
        priv = crypto.generate_private_key()
        pub_bytes = crypto.compress_pubkey(crypto.private_to_public(priv))
        pkh = crypto.hash160(pub_bytes)
        lock = script.p2pkh_lock(pkh)
        sighash = crypto.sha256(b"original")
        unlock = script.p2pkh_unlock(priv, sighash, pub_bytes)
        self.assertFalse(script.execute(unlock, lock, crypto.sha256(b"tampered")))


class TestMultisig(unittest.TestCase):
    def setUp(self):
        self.signers = [Wallet_generate() for _ in range(3)]
        self.pubkeys = [w[1] for w in self.signers]
        self.lock = script.multisig_lock(2, self.pubkeys)
        self.sighash = crypto.sha256(b"multisig tx")

    def _sig(self, idx):
        priv = self.signers[idx][0]
        r, s = crypto.sign(priv, self.sighash)
        return script.encode_sig(r, s)

    def test_2_of_3_valid(self):
        unlock = script.multisig_unlock([self._sig(0), self._sig(1)])
        self.assertTrue(script.execute(unlock, self.lock, self.sighash))

    def test_2_of_3_valid_different_pair(self):
        unlock = script.multisig_unlock([self._sig(0), self._sig(2)])
        self.assertTrue(script.execute(unlock, self.lock, self.sighash))

    def test_only_one_sig_insufficient(self):
        unlock = script.multisig_unlock([self._sig(0)])
        self.assertFalse(script.execute(unlock, self.lock, self.sighash))

    def test_out_of_order_sigs_rejected(self):
        # OP_CHECKMULTISIG requires sigs in the same relative order as keys
        unlock = script.multisig_unlock([self._sig(1), self._sig(0)])
        self.assertFalse(script.execute(unlock, self.lock, self.sighash))

    def test_duplicate_sig_does_not_count_twice(self):
        sig0 = self._sig(0)
        unlock = script.multisig_unlock([sig0, sig0])
        self.assertFalse(script.execute(unlock, self.lock, self.sighash))

    def test_nonsigner_sig_rejected(self):
        outsider = Wallet_generate()
        r, s = crypto.sign(outsider[0], self.sighash)
        forged = script.encode_sig(r, s)
        unlock = script.multisig_unlock([self._sig(0), forged])
        self.assertFalse(script.execute(unlock, self.lock, self.sighash))


class TestScriptRobustness(unittest.TestCase):
    def test_empty_scripts_fail_safely(self):
        self.assertFalse(script.execute([], [], b"\x00" * 32))

    def test_malformed_opcode_fails_safely(self):
        self.assertFalse(script.execute([], ["OP_NOT_A_REAL_OPCODE"], b"\x00" * 32))

    def test_stack_underflow_fails_safely_not_crash(self):
        # OP_EQUALVERIFY with nothing on the stack should return False, not raise
        self.assertFalse(script.execute([], ["OP_EQUALVERIFY"], b"\x00" * 32))

    def test_leftover_stack_items_fail(self):
        # a locking script that leaves 2 items on the stack should not "succeed"
        self.assertFalse(script.execute(["01", "02"], [], b"\x00" * 32))

    def test_garbage_hex_push_fails_safely_not_crash(self):
        # invalid hex in a data push should be caught internally and just
        # fail the script (return False), not propagate a raw exception
        lock = ["OP_CHECKSIG"]
        unlock = ["deadbeef", "not-valid-hex-zz"]
        self.assertFalse(script.execute(unlock, lock, b"\x00" * 32))


def Wallet_generate():
    priv = crypto.generate_private_key()
    pub_bytes = crypto.compress_pubkey(crypto.private_to_public(priv))
    return priv, pub_bytes


if __name__ == "__main__":
    unittest.main()
