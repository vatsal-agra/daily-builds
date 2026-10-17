// Package bwt implements the block-sorting compressor: Burrows–Wheeler transform
// (cyclic rotations sorted by prefix doubling with counting sort), move-to-front,
// zero-run-length coding in bijective base 2 (RUNA/RUNB), and canonical Huffman.
package bwt

import "errors"

// Transform returns the last column of the sorted cyclic rotations of s and the
// row index at which the original string appears.
func Transform(s []byte) (last []byte, primary int) {
	n := len(s)
	if n == 0 {
		return nil, 0
	}
	sa := sortRotations(s)
	last = make([]byte, n)
	primary = -1
	for i, p := range sa {
		if p == 0 {
			if primary < 0 {
				primary = i
			}
			last[i] = s[n-1]
		} else {
			last[i] = s[p-1]
		}
	}
	return last, primary
}

// sortRotations returns rotation start offsets in lexicographic order of the rotations.
func sortRotations(s []byte) []int32 {
	n := len(s)
	sa := make([]int32, n)
	rank := make([]int32, n)
	tmp := make([]int32, n)
	nrank := make([]int32, n)
	m := 256
	if n > m {
		m = n
	}
	cnt := make([]int32, m+1)
	for _, c := range s {
		cnt[c]++
	}
	for i := 1; i < 256; i++ {
		cnt[i] += cnt[i-1]
	}
	for i := n - 1; i >= 0; i-- {
		cnt[s[i]]--
		sa[cnt[s[i]]] = int32(i)
	}
	classes := 1
	rank[sa[0]] = 0
	for i := 1; i < n; i++ {
		if s[sa[i]] != s[sa[i-1]] {
			classes++
		}
		rank[sa[i]] = int32(classes - 1)
	}
	for k := 1; k < n && classes < n; k <<= 1 {
		for i := 0; i < n; i++ {
			p := int(sa[i]) - k
			if p < 0 {
				p += n
			}
			tmp[i] = int32(p)
		}
		for i := 0; i < classes+1; i++ {
			cnt[i] = 0
		}
		for i := 0; i < n; i++ {
			cnt[rank[tmp[i]]]++
		}
		for i := 1; i < classes; i++ {
			cnt[i] += cnt[i-1]
		}
		for i := n - 1; i >= 0; i-- {
			r := rank[tmp[i]]
			cnt[r]--
			sa[cnt[r]] = tmp[i]
		}
		nrank[sa[0]] = 0
		classes = 1
		for i := 1; i < n; i++ {
			a, b := int(sa[i]), int(sa[i-1])
			a2, b2 := a+k, b+k
			if a2 >= n {
				a2 -= n
			}
			if b2 >= n {
				b2 -= n
			}
			if rank[a] != rank[b] || rank[a2] != rank[b2] {
				classes++
			}
			nrank[a] = int32(classes - 1)
		}
		rank, nrank = nrank, rank
	}
	return sa
}

// ErrBadPrimary is returned when the primary index is out of range.
var ErrBadPrimary = errors.New("bwt: primary index out of range")

// Inverse reverses Transform.
func Inverse(last []byte, primary int) ([]byte, error) {
	n := len(last)
	if n == 0 {
		return nil, nil
	}
	if primary < 0 || primary >= n {
		return nil, ErrBadPrimary
	}
	var c [256]int32
	for _, b := range last {
		c[b]++
	}
	var start [256]int32
	sum := int32(0)
	for i := 0; i < 256; i++ {
		start[i] = sum
		sum += c[i]
	}
	lf := make([]int32, n)
	var seen [256]int32
	for i, b := range last {
		lf[i] = start[b] + seen[b]
		seen[b]++
	}
	out := make([]byte, n)
	r := int32(primary)
	for j := n - 1; j >= 0; j-- {
		out[j] = last[r]
		r = lf[r]
	}
	return out, nil
}
