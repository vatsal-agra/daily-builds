"""UTXO-model transactions: inputs reference a previous transaction's output
by (txid, index) and carry a signature + pubkey unlocking it; outputs lock a
value to an address. Canonical binary serialization drives both the
transaction id and the signature hash.
"""

from dataclasses import dataclass, field

from bedrock import binfmt
from bedrock.crypto import (
    sha256d, sign as ecdsa_sign, verify as ecdsa_verify,
    encode_signature, decode_signature, compress_pubkey, pubkey_to_address,
)

COINBASE_PREV_TXID = "00" * 32
COINBASE_PREV_INDEX = 0xFFFFFFFF


class TransactionError(ValueError):
    pass


@dataclass
class TxOutput:
    value: int
    address: str

    def to_bytes(self) -> bytes:
        if self.value < 0:
            raise TransactionError("output value cannot be negative")
        return binfmt.write_varint(self.value) + binfmt.write_str(self.address)

    @staticmethod
    def from_bytes(buf: bytes, offset: int):
        value, offset = binfmt.read_varint(buf, offset)
        address, offset = binfmt.read_str(buf, offset)
        return TxOutput(value, address), offset


@dataclass
class TxInput:
    prev_txid: str
    prev_index: int
    pubkey: bytes = None      # compressed public key bytes, 33 bytes
    signature: bytes = None   # 64-byte (r, s) encoding

    def to_bytes(self) -> bytes:
        out = bytes.fromhex(self.prev_txid)
        if len(out) != 32:
            raise TransactionError("prev_txid must be 32 bytes")
        out += binfmt.write_varint(self.prev_index)
        out += binfmt.write_bytes(self.signature or b"")
        out += binfmt.write_bytes(self.pubkey or b"")
        return out

    @staticmethod
    def from_bytes(buf: bytes, offset: int):
        prev_txid = buf[offset:offset + 32].hex()
        offset += 32
        prev_index, offset = binfmt.read_varint(buf, offset)
        sig, offset = binfmt.read_bytes(buf, offset)
        pubkey, offset = binfmt.read_bytes(buf, offset)
        return TxInput(prev_txid, prev_index, pubkey or None, sig or None), offset

    @property
    def is_coinbase_marker(self) -> bool:
        return self.prev_txid == COINBASE_PREV_TXID and self.prev_index == COINBASE_PREV_INDEX


@dataclass
class Transaction:
    version: int
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    coinbase_data: bytes = None  # non-None iff this is a coinbase transaction

    @property
    def is_coinbase(self) -> bool:
        return self.coinbase_data is not None

    def to_bytes(self) -> bytes:
        out = binfmt.write_varint(self.version)
        out += binfmt.write_varint(len(self.inputs))
        for tx_in in self.inputs:
            out += tx_in.to_bytes()
        out += binfmt.write_varint(len(self.outputs))
        for tx_out in self.outputs:
            out += tx_out.to_bytes()
        out += binfmt.write_bytes(self.coinbase_data or b"")
        return out

    @staticmethod
    def from_bytes(buf: bytes, offset: int = 0):
        version, offset = binfmt.read_varint(buf, offset)
        n_in, offset = binfmt.read_varint(buf, offset)
        inputs = []
        for _ in range(n_in):
            tx_in, offset = TxInput.from_bytes(buf, offset)
            inputs.append(tx_in)
        n_out, offset = binfmt.read_varint(buf, offset)
        outputs = []
        for _ in range(n_out):
            tx_out, offset = TxOutput.from_bytes(buf, offset)
            outputs.append(tx_out)
        coinbase_data, offset = binfmt.read_bytes(buf, offset)
        return Transaction(version, inputs, outputs, coinbase_data or None), offset

    @property
    def txid(self) -> str:
        return sha256d(self.to_bytes()).hex()

    def sighash(self) -> bytes:
        """The hash every input's owner signs: a *skeleton* serialization
        that commits to which utxos are being spent (prev_txid/prev_index
        only — no pubkey or signature bytes) and where the funds go, but
        deliberately nothing about signing status. This is what lets inputs
        be signed in any order or independently by different owners: if the
        sighash included other inputs' pubkey bytes (set only once *those*
        inputs are signed), signing input B after input A would silently
        change the very digest input A's signature was already computed
        over, invalidating it. Every input signs this same digest."""
        out = binfmt.write_varint(self.version)
        out += binfmt.write_varint(len(self.inputs))
        for tx_in in self.inputs:
            out += bytes.fromhex(tx_in.prev_txid)
            out += binfmt.write_varint(tx_in.prev_index)
        out += binfmt.write_varint(len(self.outputs))
        for tx_out in self.outputs:
            out += tx_out.to_bytes()
        out += binfmt.write_bytes(self.coinbase_data or b"")
        return sha256d(out)

    def sign_input(self, index: int, private_key: int, pubkey) -> None:
        tx_in = self.inputs[index]
        tx_in.pubkey = compress_pubkey(pubkey)
        digest = self.sighash()
        sig = ecdsa_sign(private_key, digest)
        tx_in.signature = encode_signature(sig)

    def verify_input_signature(self, index: int) -> bool:
        tx_in = self.inputs[index]
        if not tx_in.pubkey or not tx_in.signature:
            return False
        from bedrock.crypto import decompress_pubkey
        try:
            pubkey = decompress_pubkey(tx_in.pubkey)
            sig = decode_signature(tx_in.signature)
        except ValueError:
            return False
        return ecdsa_verify(pubkey, self.sighash(), sig)

    def input_owner_address(self, index: int) -> str:
        from bedrock.crypto import decompress_pubkey
        tx_in = self.inputs[index]
        if not tx_in.pubkey:
            raise TransactionError("input has no pubkey")
        return pubkey_to_address(decompress_pubkey(tx_in.pubkey))

    @staticmethod
    def new_coinbase(reward_address: str, value: int, height: int, extra: bytes = b"") -> "Transaction":
        import secrets
        coinbase_data = binfmt.write_varint(height) + secrets.token_bytes(8) + extra
        return Transaction(
            version=1,
            inputs=[],
            outputs=[TxOutput(value=value, address=reward_address)],
            coinbase_data=coinbase_data,
        )

    def total_output_value(self) -> int:
        return sum(o.value for o in self.outputs)
