"""A narrated, single-process walkthrough of Vein's core: real secp256k1
keys, a real P2PKH spend validated by the Script VM, and real proof-of-
work mining with difficulty retargeting — everything except the P2P layer
(see partition_demo.py for that).
"""

from __future__ import annotations

import time

from ..core.block import Block, BlockHeader, target_to_bits, MAX_TARGET
from ..core.chain import Blockchain, ChainParams, make_coinbase, ValidationError, subsidy_at_height
from ..core.mempool import Mempool
from ..core.script import Script, execute
from ..core.transaction import Transaction, TxIn, TxOut, merkle_root
from ..crypto.curve import derive_pubkey
from ..crypto.ecdsa import generate_privkey, sign, verify
from ..crypto.address import serialize_pubkey, address_from_pubkey
from ..crypto.hashes import hash160, sha256


def _p(msg: str = "") -> None:
    print(msg)


def _mine_header(header: BlockHeader) -> int:
    target = header.target()
    nonce = 0
    tries = 0
    t0 = time.time()
    while True:
        header.nonce = nonce & 0xFFFFFFFF
        tries += 1
        if int.from_bytes(header.hash(), "big") <= target:
            return tries, time.time() - t0
        nonce += 1


def run_core_demo() -> None:
    _p("=" * 72)
    _p("VEIN — from-scratch Proof-of-Work blockchain: core walkthrough")
    _p("=" * 72)

    _p("\n[1/4] secp256k1 + ECDSA + Base58Check addresses, all from scratch")
    _p("-" * 72)
    alice_priv = generate_privkey()
    alice_pub = serialize_pubkey(derive_pubkey(alice_priv))
    alice_addr = address_from_pubkey(alice_pub)
    bob_priv = generate_privkey()
    bob_pub = serialize_pubkey(derive_pubkey(bob_priv))
    bob_addr = address_from_pubkey(bob_pub)
    _p(f"  Alice's address: {alice_addr}")
    _p(f"  Bob's address:   {bob_addr}")

    msg_hash = sha256(b"a message only Alice's key can sign")
    sig = sign(alice_priv, msg_hash)
    assert verify(derive_pubkey(alice_priv), msg_hash, sig)
    assert not verify(derive_pubkey(bob_priv), msg_hash, sig)
    _p("  signed a message with Alice's key, verified against Alice's pubkey: OK")
    _p("  same signature verified against Bob's pubkey: correctly rejected")

    _p("\n[2/4] Genesis + proof-of-work mining with a real nonce search")
    _p("-" * 72)
    params = ChainParams(
        initial_bits=target_to_bits(MAX_TARGET >> 11),
        retarget_interval=4,
        target_block_time=3.0,
    )
    chain = Blockchain(params)
    mempool = Mempool(chain)
    _p(f"  genesis hash: {chain.tip_hash.hex()}")
    _p(f"  target: 2^256 >> 11 (~{2**11:,} expected hash attempts per block)")

    miner_pkh = hash160(alice_pub)
    t = int(time.time())
    for i in range(1, 6):
        cb = make_coinbase(chain.height + 1, subsidy_at_height(chain.height + 1, params), miner_pkh, extra_nonce=i)
        bits = chain.expected_bits_after(chain.tip_hash)
        header = BlockHeader(1, chain.tip_hash, merkle_root([cb.txid()]), t + i, bits, 0)
        tries, elapsed = _mine_header(header)
        block = Block(header, [cb])
        changed = chain.add_block(block, now=t + i + 1)
        assert changed
        _p(f"  mined block {chain.height} in {tries:,} tries ({elapsed:.2f}s, "
           f"{tries/max(elapsed,1e-6):,.0f} h/s) bits={header.bits:#x} hash={block.hash().hex()[:16]}")

    _p(f"\n  Alice's balance after mining {chain.height} blocks: "
       f"{chain.balance_of(miner_pkh):,} sats ({chain.balance_of(miner_pkh)/1e8:.2f} VEIN)")

    _p("\n[3/4] A real UTXO spend: Alice pays Bob, validated by the Script VM")
    _p("-" * 72)
    utxos = chain.utxos_for(miner_pkh)
    (txid, idx), prevout = utxos[0]
    _p(f"  spending output {txid.hex()[:16]}:{idx} worth {prevout.value:,} sats")

    pay_amount = 12_34500000
    fee = 1000
    change = prevout.value - pay_amount - fee
    tx = Transaction(
        inputs=[TxIn(txid, idx, Script([]))],
        outputs=[TxOut(pay_amount, Script.p2pkh_lock(hash160(bob_pub))),
                 TxOut(change, Script.p2pkh_lock(miner_pkh))],
    )
    tx.sign_input(0, alice_priv, prevout.script_pubkey, alice_pub)
    checker = tx.make_sig_checker(0, prevout.script_pubkey)
    ok = execute(tx.inputs[0].script_sig, prevout.script_pubkey, checker)
    _p(f"  script execution (OP_DUP OP_HASH160 <hash> OP_EQUALVERIFY OP_CHECKSIG): {'VALID' if ok else 'INVALID'}")
    assert ok

    mempool.add_transaction(tx)
    _p(f"  accepted into mempool (fee={fee} sats)")

    # Show a tampered clone is correctly rejected before it ever reaches a block.
    tampered = Transaction.deserialize(tx.serialize())
    tampered.outputs[0].value += 1
    try:
        checker2 = tampered.make_sig_checker(0, prevout.script_pubkey)
        ok2 = execute(tampered.inputs[0].script_sig, prevout.script_pubkey, checker2)
    except Exception:
        ok2 = False
    _p(f"  tampering with the output value after signing: script now {'VALID' if ok2 else 'INVALID (correctly rejected)'}")
    assert not ok2

    cb2 = make_coinbase(chain.height + 1, subsidy_at_height(chain.height + 1, params), miner_pkh, extra_nonce=99)
    all_txs = [cb2, tx]
    bits = chain.expected_bits_after(chain.tip_hash)
    header = BlockHeader(1, chain.tip_hash, merkle_root([x.txid() for x in all_txs]), t + 10, bits, 0)
    tries, elapsed = _mine_header(header)
    block = Block(header, all_txs)
    changed = chain.add_block(block, now=t + 11)
    assert changed
    mempool.remove_confirmed([tx.txid()])
    _p(f"  confirmed in block {chain.height} ({tries:,} tries)")
    _p(f"  Bob's balance:   {chain.balance_of(hash160(bob_pub)):,} sats")
    _p(f"  Alice's balance: {chain.balance_of(miner_pkh):,} sats")
    assert chain.balance_of(hash160(bob_pub)) == pay_amount

    _p("\n[4/4] Difficulty retargeting reacts to measured block time")
    _p("-" * 72)
    bits_history = []
    tt = t + 20
    for i in range(params.retarget_interval * 2):
        cb = make_coinbase(chain.height + 1, subsidy_at_height(chain.height + 1, params), miner_pkh, extra_nonce=200 + i)
        bits = chain.expected_bits_after(chain.tip_hash)
        header = BlockHeader(1, chain.tip_hash, merkle_root([cb.txid()]), tt, bits, 0)
        tries, elapsed = _mine_header(header)
        block = Block(header, [cb])
        chain.add_block(block, now=tt + 1)
        bits_history.append(header.bits)
        tt += 1  # deliberately faster than target_block_time -> difficulty should rise
    _p(f"  bits before 2nd retarget interval: {bits_history[0]:#x}")
    _p(f"  bits after:                        {bits_history[-1]:#x}")
    _p("  (mining faster than the target block time makes the target shrink —")
    _p("   i.e. the puzzle gets harder — exactly like real difficulty retargeting)")

    _p("\n" + "=" * 72)
    _p("CORE DEMO COMPLETE — all 4 required features exercised end-to-end.")
    _p("=" * 72)
