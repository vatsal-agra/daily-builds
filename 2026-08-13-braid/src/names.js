// names.js — allocates a display name for each new peer, and NEVER reuses
// one within a session, even after that peer is removed. This matters for
// more than cosmetics: a peer's display name doubles as its CRDT site id,
// and a fresh Peer's id-counter always restarts at 0. Reusing a name means
// minting ids identical to ones the old peer already used — every other
// replica already has those exact ids and silently no-ops them as
// "already applied" (see Doc._applyInsert's idempotency check), so the new
// peer's first several keystrokes would vanish everywhere with no error.

export const NAME_POOL = ['Alice', 'Bob', 'Carol', 'Dave', 'Eve', 'Frank', 'Grace', 'Heidi', 'Ivan', 'Judy'];

export class NameAllocator {
  constructor() {
    this.everUsed = new Set();
  }

  /** Returns a name never handed out before by this allocator, and marks
   * it used permanently (removal must NOT free it back up). */
  next() {
    for (const n of NAME_POOL) {
      if (!this.everUsed.has(n)) {
        this.everUsed.add(n);
        return n;
      }
    }
    let i = this.everUsed.size + 1;
    while (this.everUsed.has(`Peer${i}`)) i++;
    const name = `Peer${i}`;
    this.everUsed.add(name);
    return name;
  }
}
