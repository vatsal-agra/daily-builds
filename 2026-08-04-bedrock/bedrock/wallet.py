"""Wallets: a keypair + address, plus simple coin selection for building and
signing a transaction against a chain's UTXO set."""

from dataclasses import dataclass, field

from bedrock import crypto
from bedrock.transaction import Transaction, TxInput, TxOutput


class WalletError(ValueError):
    pass


@dataclass
class Wallet:
    private_key: int
    public_key: tuple = field(init=False)
    address: str = field(init=False)

    def __post_init__(self):
        self.public_key = crypto.derive_public_key(self.private_key)
        self.address = crypto.pubkey_to_address(self.public_key)

    @staticmethod
    def generate() -> "Wallet":
        return Wallet(crypto.generate_private_key())

    @staticmethod
    def from_wif(private_key_hex: str) -> "Wallet":
        return Wallet(int(private_key_hex, 16))

    def to_wif(self) -> str:
        return f"{self.private_key:064x}"

    def balance(self, chain) -> int:
        return chain.utxo_set.balance(self.address)

    def build_transaction(self, chain, to_address: str, amount: int, fee: int = 0, mempool=None) -> Transaction:
        if amount <= 0:
            raise WalletError("amount must be positive")
        if fee < 0:
            raise WalletError("fee cannot be negative")
        if not crypto.is_valid_address(to_address):
            raise WalletError("recipient address fails checksum validation")

        reserved = mempool.reserved if mempool is not None else set()
        available = [
            (key, out) for key, out in chain.utxo_set.utxos_for_address(self.address)
            if key not in reserved
        ]
        needed = amount + fee
        selected, running = [], 0
        for key, out in available:
            selected.append(key)
            running += out.value
            if running >= needed:
                break
        if running < needed:
            raise WalletError(
                f"insufficient funds: have {running}, need {needed}"
            )

        tx = Transaction(
            version=1,
            inputs=[TxInput(prev_txid=k[0], prev_index=k[1]) for k in selected],
            outputs=[TxOutput(value=amount, address=to_address)],
        )
        change = running - needed
        if change > 0:
            tx.outputs.append(TxOutput(value=change, address=self.address))
        for idx in range(len(tx.inputs)):
            tx.sign_input(idx, self.private_key, self.public_key)
        return tx

    def send(self, chain, mempool, to_address: str, amount: int, fee: int = 0) -> Transaction:
        tx = self.build_transaction(chain, to_address, amount, fee=fee, mempool=mempool)
        mempool.add_transaction(tx, chain)
        return tx
