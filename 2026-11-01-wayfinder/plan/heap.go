// Package plan implements the path planners: Dijkstra, A*, Jump Point Search,
// Theta*, D* Lite and HPA*.
package plan

import "math"

// Key is a two-level priority (lexicographic, smaller first).
type Key [2]float64

func (a Key) less(b Key) bool { return a.lessTol(b) }

// lessTol orders keys lexicographically, tolerant to float rounding in the first component: sums of
// the same step costs taken in different orders differ in the last bits, and
// D* Lite's termination test must treat such keys as equal.
func (a Key) lessTol(b Key) bool {
	if math.Abs(a[0]-b[0]) > 1e-9 {
		return a[0] < b[0]
	}
	return a[1] < b[1]-1e-9
}

// Heap is an indexed binary min-heap over node ids 0..n-1 supporting
// insert, decrease/increase-key (Update) and removal.
type Heap struct {
	ids []int32
	key []Key
	pos []int32 // pos[id] = index in ids, or -1
}

// NewHeap makes a heap for ids in [0,n).
func NewHeap(n int) *Heap {
	h := &Heap{key: make([]Key, n), pos: make([]int32, n)}
	for i := range h.pos {
		h.pos[i] = -1
	}
	return h
}

// Len returns the number of queued ids.
func (h *Heap) Len() int { return len(h.ids) }

// Has reports whether id is queued.
func (h *Heap) Has(id int) bool { return h.pos[id] >= 0 }

// Update inserts id or changes its key.
func (h *Heap) Update(id int, k Key) {
	if p := h.pos[id]; p >= 0 {
		old := h.key[id]
		h.key[id] = k
		if k.less(old) {
			h.up(int(p))
		} else {
			h.down(int(p))
		}
		return
	}
	h.key[id] = k
	h.ids = append(h.ids, int32(id))
	h.pos[id] = int32(len(h.ids) - 1)
	h.up(len(h.ids) - 1)
}

// Peek returns the minimum id and key without removing it.
func (h *Heap) Peek() (int, Key) { return int(h.ids[0]), h.key[h.ids[0]] }

// Pop removes and returns the minimum id.
func (h *Heap) Pop() int {
	id := h.ids[0]
	h.remove(0)
	return int(id)
}

// Remove deletes id if present.
func (h *Heap) Remove(id int) {
	if p := h.pos[id]; p >= 0 {
		h.remove(int(p))
	}
}

func (h *Heap) remove(i int) {
	last := len(h.ids) - 1
	h.swap(i, last)
	h.pos[h.ids[last]] = -1
	h.ids = h.ids[:last]
	if i < last {
		h.down(i)
		h.up(i)
	}
}

func (h *Heap) swap(i, j int) {
	h.ids[i], h.ids[j] = h.ids[j], h.ids[i]
	h.pos[h.ids[i]] = int32(i)
	h.pos[h.ids[j]] = int32(j)
}

func (h *Heap) up(i int) {
	for i > 0 {
		p := (i - 1) / 2
		if !h.key[h.ids[i]].less(h.key[h.ids[p]]) {
			return
		}
		h.swap(i, p)
		i = p
	}
}

func (h *Heap) down(i int) {
	n := len(h.ids)
	for {
		l, r, m := 2*i+1, 2*i+2, i
		if l < n && h.key[h.ids[l]].less(h.key[h.ids[m]]) {
			m = l
		}
		if r < n && h.key[h.ids[r]].less(h.key[h.ids[m]]) {
			m = r
		}
		if m == i {
			return
		}
		h.swap(i, m)
		i = m
	}
}
