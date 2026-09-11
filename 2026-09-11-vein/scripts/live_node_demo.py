#!/usr/bin/env python3
"""Starts one real Vein node (real threads, real sockets, real mining),
exercises the wallet CLI against its live RPC (new/address/balance/send),
confirms a real payment, then runs the block-explorer headless-browser
smoke test against that same running node. Exits 0 only if every step
succeeds. Used by demo.sh; also runnable directly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vein.core.chain import ChainParams
from vein.core.block import target_to_bits, MAX_TARGET
from vein.node.server import VeinNode
from vein.wallet.wallet import Wallet

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P2P_PORT, RPC_PORT = 19800, 19900
RPC = f"http://127.0.0.1:{RPC_PORT}"


def run_cli(*args, expect_ok=True):
    cmd = [sys.executable, "-m", "vein.cli", *args]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
    print(f"    $ vein {' '.join(args)}")
    if result.stdout.strip():
        print("      " + result.stdout.strip().replace("\n", "\n      "))
    if expect_ok and result.returncode != 0:
        print("      STDERR: " + result.stderr.strip())
        raise SystemExit(f"command failed: vein {' '.join(args)}")
    return result


def main() -> int:
    params = ChainParams(
        initial_bits=target_to_bits(MAX_TARGET >> 10),
        retarget_interval=8,
        target_block_time=2.0,
        halving_interval=64,
    )
    wallet_a = Wallet.generate()
    node = VeinNode(params, "127.0.0.1", P2P_PORT, "127.0.0.1", RPC_PORT, wallet_a.pubkey_hash,
                     node_name="demo")
    node.start(mine=True)
    print(f"  node started: p2p=127.0.0.1:{P2P_PORT} rpc={RPC}, mining to {wallet_a.address}")

    try:
        t0 = time.time()
        while node.chain.balance_of(wallet_a.pubkey_hash) == 0 and time.time() - t0 < 60:
            time.sleep(0.3)
        balance = node.chain.balance_of(wallet_a.pubkey_hash)
        if balance == 0:
            print("  FAIL: miner wallet never received a block reward")
            return 1
        print(f"  miner wallet funded: {balance:,} sats after height {node.chain.height}")

        wallet_a_path = "/tmp/vein_demo_wallet_a.json"
        wallet_b_path = "/tmp/vein_demo_wallet_b.json"
        wallet_a.save(wallet_a_path)
        run_cli("wallet", "new", "--out", wallet_b_path)
        b_addr = run_cli("wallet", "address", "--wallet", wallet_b_path).stdout.strip()

        run_cli("wallet", "balance", "--wallet", wallet_a_path, "--rpc", RPC)
        send_amount = 5_00000000
        run_cli("wallet", "send", "--wallet", wallet_a_path, "--rpc", RPC,
                "--to", b_addr, "--amount", str(send_amount), "--fee", "500")

        node.miner.notify_new_work()
        t0 = time.time()
        while node.chain.balance_of(Wallet.load(wallet_b_path).pubkey_hash) == 0 and time.time() - t0 < 60:
            time.sleep(0.3)
        b_balance = node.chain.balance_of(Wallet.load(wallet_b_path).pubkey_hash)
        if b_balance != send_amount:
            print(f"  FAIL: recipient balance is {b_balance}, expected exactly {send_amount}")
            return 1
        print(f"  payment confirmed: recipient balance = {b_balance:,} sats")

        # --- explorer headless-browser check against this same live node ---
        explorer_out = "/tmp/vein_demo_explorer.html"
        run_cli("explorer", "--rpc", RPC, "--out", explorer_out)

        node_path = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        env = dict(os.environ)
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
        if node_path:
            env["NODE_PATH"] = node_path
        smoke_script = os.path.join(PROJECT_ROOT, "tests", "explorer_smoke.js")
        result = subprocess.run(["node", smoke_script, explorer_out, b_addr],
                                 capture_output=True, text=True, env=env, timeout=60)
        print("    " + result.stdout.strip().replace("\n", "\n    "))
        if result.returncode != 0:
            print("    " + result.stderr.strip())
            print("  FAIL: explorer headless-browser smoke test")
            return 1
        print("  explorer smoke test passed")

        return 0
    finally:
        node.stop()


if __name__ == "__main__":
    sys.exit(main())
