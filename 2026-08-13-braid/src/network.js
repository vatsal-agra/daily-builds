// network.js — a deliberately adversarial simulated network between peers.
//
// Two clock implementations are provided:
//  - RealClock: wraps setTimeout, for the live browser demo (messages
//    actually arrive "later", so you can watch merges happen over time).
//  - VirtualClock: a discrete-event simulator with no wall-clock waiting
//    at all — schedule() just records "deliver this at virtual time T",
//    and runAll() drains the queue in time order. This is what lets the
//    test suite run thousands of randomized latency/reordering scenarios
//    in milliseconds instead of real seconds.

export class RealClock {
  schedule(cb, delayMs) {
    setTimeout(cb, Math.max(0, delayMs));
  }
}

export class VirtualClock {
  constructor() {
    this.queue = [];
    this.time = 0;
    this._seq = 0;
  }
  schedule(cb, delayMs) {
    this.queue.push({ time: this.time + Math.max(0, delayMs), seq: this._seq++, cb });
  }
  /** Drain every scheduled event, in time order, including new events
   * scheduled by callbacks as they run. Guards against runaway loops. */
  runAll(maxEvents = 200000) {
    let n = 0;
    while (this.queue.length) {
      if (++n > maxEvents) throw new Error('VirtualClock.runAll: exceeded maxEvents (possible infinite loop)');
      // stable-ish pick of earliest (time, seq)
      let bestIdx = 0;
      for (let i = 1; i < this.queue.length; i++) {
        const a = this.queue[i], b = this.queue[bestIdx];
        if (a.time < b.time || (a.time === b.time && a.seq < b.seq)) bestIdx = i;
      }
      const [ev] = this.queue.splice(bestIdx, 1);
      this.time = ev.time;
      ev.cb();
    }
  }
}

const DEFAULT_PARTITION = '__default__';

export class Network {
  constructor({ clock, minLatency = 15, maxLatency = 120, lossRate = 0, rng = Math.random } = {}) {
    this.clock = clock || new RealClock();
    this.minLatency = minLatency;
    this.maxLatency = maxLatency;
    this.lossRate = lossRate;
    this.rng = rng;
    this.peers = new Map(); // siteId -> onReceive(op)
    this.partitions = new Map(); // siteId -> group label
    this.stats = { sent: 0, delivered: 0, dropped: 0 };
    this.log = []; // {t, from, to, op, status} — for the UI's activity feed
    // Messages held up by a partition, NOT lost — a network split delays
    // delivery, it doesn't silently eat data. They get flushed the moment
    // sender and recipient land back in the same partition group. Only
    // `lossRate` represents genuine packet loss.
    this.blocked = []; // {from, to, op}
  }

  addPeer(siteId, onReceive) {
    this.peers.set(siteId, onReceive);
    this.partitions.set(siteId, DEFAULT_PARTITION);
  }

  removePeer(siteId) {
    this.peers.delete(siteId);
    this.partitions.delete(siteId);
    this.blocked = this.blocked.filter((m) => m.from !== siteId && m.to !== siteId);
  }

  /** Assign a peer to a partition group. Peers only exchange messages with
   * others in the SAME group. Use distinct group labels to simulate a
   * network split; put everyone back in the same label to "heal" it. */
  setPartition(siteId, group) {
    this.partitions.set(siteId, group);
    this._flushBlocked();
  }

  healAll() {
    for (const siteId of this.peers.keys()) this.partitions.set(siteId, DEFAULT_PARTITION);
    this._flushBlocked();
  }

  broadcast(fromSite, op) {
    this.stats.sent++;
    const fromGroup = this.partitions.get(fromSite);
    for (const [siteId, onReceive] of this.peers) {
      if (siteId === fromSite) continue;
      if (this.rng() < this.lossRate) {
        this.stats.dropped++;
        this.log.push({ t: this.clock.time ?? null, from: fromSite, to: siteId, op, status: 'dropped' });
        continue;
      }
      if (this.partitions.get(siteId) !== fromGroup) {
        // held up by the split, deliverable once the partition heals
        this.blocked.push({ from: fromSite, to: siteId, op });
        this.log.push({ t: this.clock.time ?? null, from: fromSite, to: siteId, op, status: 'blocked' });
        continue;
      }
      this._scheduleDelivery(fromSite, siteId, op);
    }
  }

  _scheduleDelivery(fromSite, toSite, op) {
    const onReceive = this.peers.get(toSite);
    const latency = this.minLatency + this.rng() * (this.maxLatency - this.minLatency);
    this.clock.schedule(() => {
      this.stats.delivered++;
      this.log.push({ t: this.clock.time ?? null, from: fromSite, to: toSite, op, status: 'delivered' });
      onReceive(op);
    }, latency);
  }

  _flushBlocked() {
    if (!this.blocked.length) return;
    const stillBlocked = [];
    for (const msg of this.blocked) {
      if (this.peers.has(msg.to) && this.partitions.get(msg.to) === this.partitions.get(msg.from)) {
        this._scheduleDelivery(msg.from, msg.to, msg.op);
      } else {
        stillBlocked.push(msg);
      }
    }
    this.blocked = stillBlocked;
  }
}
