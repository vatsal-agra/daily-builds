"""Disk persistence for the `nonce local` CLI commands: a wallet keypair
and a full chain (as an ordered list of blocks) saved as JSON, so a user
can genuinely mine and send across separate CLI invocations instead of
everything living only inside one scripted, in-memory demo run.

Loading replays every block through the real `Blockchain.add_block`
validation path (not a trusting pickle-load) — a corrupted or
hand-tampered chain file is caught exactly the same way a bad block from
the network would be.
"""

import json
import os

from .core.block import Block
from .core.blockchain import Blockchain
from .wallet import Wallet

WALLET_FILE = "wallet.json"
CHAIN_FILE = "chain.json"


def exists(data_dir: str) -> bool:
    return os.path.exists(os.path.join(data_dir, CHAIN_FILE))


def save(data_dir: str, wallet: Wallet, chain: Blockchain):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, WALLET_FILE), "w") as f:
        json.dump({"privkey": wallet.privkey}, f)
    block_hashes = chain.chain_to_genesis(chain.tip_hash)
    blocks = [chain.blocks[h].to_dict() for h in block_hashes]
    with open(os.path.join(data_dir, CHAIN_FILE), "w") as f:
        json.dump(blocks, f)


def load(data_dir: str):
    """Returns (wallet, chain), or None if no saved state exists at
    data_dir. Raises ValueError if the saved chain fails real validation
    on replay (i.e. the file was corrupted or tampered with)."""
    wallet_path = os.path.join(data_dir, WALLET_FILE)
    chain_path = os.path.join(data_dir, CHAIN_FILE)
    if not (os.path.exists(wallet_path) and os.path.exists(chain_path)):
        return None

    with open(wallet_path) as f:
        wallet = Wallet(privkey=json.load(f)["privkey"])
    with open(chain_path) as f:
        blocks_data = json.load(f)
    if not blocks_data:
        raise ValueError(f"{chain_path} contains no blocks (not even a genesis block)")

    blocks = [Block.from_dict(d) for d in blocks_data]
    chain = Blockchain(blocks[0])
    for block in blocks[1:]:
        result = chain.add_block(block)
        if result.status not in ("new_tip", "side_branch"):
            raise ValueError(f"corrupt or tampered chain file: block "
                              f"{block.hash().hex()[:12]} was {result.status} ({result.reason})")
    return wallet, chain
