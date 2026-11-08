package codec

// Intra prediction for 16x16 luma and 8x8 chroma blocks. Four modes:
//   0 DC, 1 Vertical, 2 Horizontal, 3 TrueMotion (left + top - topleft).
// Neighbours come from the *unfiltered* reconstruction of the current frame.

const numIntraModes = 4

// intraAvail reports which modes are legal given neighbour availability.
func intraModeLegal(mode int, haveLeft, haveTop bool) bool {
	switch mode {
	case 0:
		return true
	case 1:
		return haveTop
	case 2:
		return haveLeft
	case 3:
		return haveLeft && haveTop
	}
	return false
}

// predictIntra fills dst (n*n, stride n) from the plane neighbours of the block at (x,y).
func predictIntra(p *Plane, x, y, n, mode int, dst []uint8) {
	haveLeft, haveTop := x > 0, y > 0
	var top, left [16]int
	tl := 128
	if haveTop {
		for i := 0; i < n; i++ {
			top[i] = int(p.Pix[p.idx(x+i, y-1)])
		}
	}
	if haveLeft {
		for i := 0; i < n; i++ {
			left[i] = int(p.Pix[p.idx(x-1, y+i)])
		}
	}
	if haveLeft && haveTop {
		tl = int(p.Pix[p.idx(x-1, y-1)])
	}
	switch mode {
	case 0:
		sum, cnt := 0, 0
		if haveTop {
			for i := 0; i < n; i++ {
				sum += top[i]
			}
			cnt += n
		}
		if haveLeft {
			for i := 0; i < n; i++ {
				sum += left[i]
			}
			cnt += n
		}
		dc := 128
		if cnt > 0 {
			dc = (sum + cnt/2) / cnt
		}
		for i := 0; i < n*n; i++ {
			dst[i] = uint8(dc)
		}
	case 1:
		for j := 0; j < n; j++ {
			for i := 0; i < n; i++ {
				dst[j*n+i] = uint8(top[i])
			}
		}
	case 2:
		for j := 0; j < n; j++ {
			for i := 0; i < n; i++ {
				dst[j*n+i] = uint8(left[j])
			}
		}
	default:
		for j := 0; j < n; j++ {
			for i := 0; i < n; i++ {
				dst[j*n+i] = clip255(left[j] + top[i] - tl)
			}
		}
	}
}
