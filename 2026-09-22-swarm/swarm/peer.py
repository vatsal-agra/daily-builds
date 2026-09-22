"""A single peer wire connection: one TCP socket, already past the
handshake, running the real BEP-3 message loop (bitfield/have exchange,
interested/choke negotiation, request/piece transfer) against whatever is
on the other end -- which may be a completely independent OS process
speaking the same protocol with none of this module's code loaded.
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import TYPE_CHECKING, List, Optional, Tuple

from . import protocol
from .piecemanager import PieceHashMismatch

if TYPE_CHECKING:  # pragma: no cover
    from .node import Node

log = logging.getLogger("swarm.peer")

PIPELINE_DEPTH = 5


class PeerConnection:
    def __init__(self, sock, remote_peer_id: bytes, remote_addr: Tuple[str, int], node: "Node", outbound: bool):
        self.sock = sock
        self.remote_peer_id = remote_peer_id
        self.remote_addr = remote_addr
        self.node = node
        self.outbound = outbound

        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False

        self.current_piece: Optional[int] = None
        self.in_flight: List[Tuple[int, int, int]] = []  # (index, begin, length)
        self._next_begin = 0
        self._lock = threading.Lock()
        self._closed = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.send_bitfield()
        threading.Thread(target=self._run, daemon=True, name=f"peer-{self.remote_peer_id[:6].hex()}").start()

    def _run(self) -> None:
        try:
            while True:
                msg = protocol.read_message(self.sock)
                if msg is None:
                    continue  # keep-alive
                self._dispatch(msg)
        except (ConnectionError, OSError, protocol.ProtocolError) as exc:
            log.info("connection to %s (%s) ended: %s", self.remote_peer_id.hex(), self.remote_addr, exc)
        finally:
            self.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            # shutdown() is safe to call from a thread other than the one
            # blocked in recv() on this socket -- it reliably unblocks that
            # recv() with a clean EOF. Calling close() alone from another
            # thread while _run()'s recv() is still in flight is a classic
            # fd-reuse race: the fd can be closed and reassigned to an
            # unrelated socket/file elsewhere in the process before the
            # blocked recv() call returns, surfacing as a spurious
            # "Bad file descriptor" instead of a clean disconnect.
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        if self.current_piece is not None:
            self.node.piece_manager.release_piece(self.current_piece, self.remote_peer_id)
        self.node.on_peer_disconnected(self.remote_peer_id)

    # -- outgoing helpers ------------------------------------------------------

    def _send(self, msg: protocol.Message) -> None:
        try:
            protocol.send_message(self.sock, msg)
        except OSError as exc:
            log.info("send to %s failed: %s", self.remote_peer_id.hex(), exc)
            self.close()

    def send_bitfield(self) -> None:
        self._send(protocol.bitfield(self.node.piece_manager.have_bitfield_bytes()))

    def send_have(self, piece_index: int) -> None:
        self._send(protocol.have(piece_index))

    def send_choke(self) -> None:
        if not self.am_choking:
            self.am_choking = True
            self._send(protocol.choke())

    def send_unchoke(self) -> None:
        if self.am_choking:
            self.am_choking = False
            self._send(protocol.unchoke())
            self._fill_pipeline()

    def _send_interested_if_needed(self) -> None:
        interesting = self.node.piece_manager.peer_is_interesting(self.remote_peer_id)
        log.debug("interest check for %s: interesting=%s am_interested=%s", self.remote_peer_id.hex()[:8], interesting, self.am_interested)
        if interesting and not self.am_interested:
            self.am_interested = True
            self._send(protocol.interested())
        elif not interesting and self.am_interested:
            self.am_interested = False
            self._send(protocol.not_interested())

    # -- dispatch ---------------------------------------------------------------

    def _dispatch(self, msg: protocol.ParsedMessage) -> None:
        log.debug("recv from %s: %s", self.remote_peer_id.hex()[:8], msg)
        if isinstance(msg, protocol.SimpleMsg):
            if msg.id == protocol.MSG_CHOKE:
                self.peer_choking = True
                if self.current_piece is not None:
                    self.node.piece_manager.release_piece(self.current_piece, self.remote_peer_id)
                self.current_piece = None
                self.in_flight.clear()
            elif msg.id == protocol.MSG_UNCHOKE:
                self.peer_choking = False
                self._fill_pipeline()
            elif msg.id == protocol.MSG_INTERESTED:
                self.peer_interested = True
                self.node.on_peer_interest_changed(self)
            elif msg.id == protocol.MSG_NOT_INTERESTED:
                self.peer_interested = False
                self.node.on_peer_interest_changed(self)
        elif isinstance(msg, protocol.BitfieldMsg):
            self.node.piece_manager.set_peer_bitfield(self.remote_peer_id, msg.bits)
            self._send_interested_if_needed()
            self.node.emit({"type": "bitfield", "peer": self.remote_peer_id.hex(), "addr": self.remote_addr})
        elif isinstance(msg, protocol.HaveMsg):
            self.node.piece_manager.mark_peer_has(self.remote_peer_id, msg.piece_index)
            self._send_interested_if_needed()
        elif isinstance(msg, protocol.RequestMsg):
            self._handle_request(msg)
        elif isinstance(msg, protocol.PieceMsg):
            self._handle_piece(msg)
        elif isinstance(msg, protocol.CancelMsg):
            pass  # uploads here are synchronous (see _handle_request), nothing queued to cancel

    def _handle_request(self, msg: protocol.RequestMsg) -> None:
        if self.am_choking:
            return  # peer must respect choke state; silently drop rather than reward violation
        try:
            block = self.node.piece_manager.read_block_for_upload(msg.index, msg.begin, msg.length)
        except (ValueError, IndexError, OSError) as exc:
            log.warning("cannot serve request %s from %s: %s", msg, self.remote_peer_id.hex(), exc)
            return
        self._send(protocol.piece(msg.index, msg.begin, block))
        self.node.piece_manager.record_upload(self.remote_peer_id, len(block))
        self.node.emit(
            {
                "type": "upload",
                "peer": self.remote_peer_id.hex(),
                "piece": msg.index,
                "bytes": len(block),
            }
        )

    def _handle_piece(self, msg: protocol.PieceMsg) -> None:
        self.in_flight = [b for b in self.in_flight if b != (msg.index, msg.begin, len(msg.block))]
        try:
            complete = self.node.piece_manager.receive_block(msg.index, msg.begin, msg.block, self.remote_peer_id)
        except PieceHashMismatch as exc:
            log.warning("%s", exc)
            self.node.emit({"type": "hash_mismatch", "peer": self.remote_peer_id.hex(), "piece": msg.index})
            self.current_piece = None
            self.in_flight.clear()
            self._fill_pipeline()
            return
        self.node.emit(
            {
                "type": "block",
                "peer": self.remote_peer_id.hex(),
                "piece": msg.index,
                "bytes": len(msg.block),
            }
        )
        if complete:
            self.node.emit({"type": "piece_complete", "peer": self.remote_peer_id.hex(), "piece": msg.index})
            self.node.broadcast_have(msg.index)
            self.current_piece = None
        self._fill_pipeline()

    # -- download-side pipelining ---------------------------------------------

    def _fill_pipeline(self) -> None:
        if self.peer_choking or not self.am_interested:
            log.debug("_fill_pipeline no-op for %s: peer_choking=%s am_interested=%s", self.remote_peer_id.hex()[:8], self.peer_choking, self.am_interested)
            return
        pm = self.node.piece_manager
        if self.current_piece is None:
            idx = pm.choose_piece_for_peer(self.remote_peer_id)
            log.debug("choose_piece_for_peer(%s) -> %s", self.remote_peer_id.hex()[:8], idx)
            if idx is None:
                self._send_interested_if_needed()  # may now be false-> sends not_interested
                return
            self.current_piece = idx
            self._blocks_remaining = list(pm.blocks_for_piece(idx))
        while len(self.in_flight) < PIPELINE_DEPTH and getattr(self, "_blocks_remaining", []):
            begin, length = self._blocks_remaining.pop(0)
            self.in_flight.append((self.current_piece, begin, length))
            log.debug("requesting piece=%s begin=%s from %s", self.current_piece, begin, self.remote_peer_id.hex()[:8])
            self._send(protocol.request(self.current_piece, begin, length))
