package deflate

var lenBase = [29]uint16{3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258}
var lenExtra = [29]uint8{0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0}
var distBase = [30]uint16{1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577}
var distExtra = [30]uint8{0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13}

// order in which code-length-code lengths are transmitted
var clOrder = [19]int{16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15}

var lenCode [259]uint8    // match length -> index into lenBase
var distCode [32769]uint8 // distance -> index into distBase

func init() {
	for c := 0; c < 29; c++ {
		hi := 258
		if c < 28 {
			hi = int(lenBase[c+1]) - 1
		}
		for l := int(lenBase[c]); l <= hi; l++ {
			lenCode[l] = uint8(c)
		}
	}
	lenCode[258] = 28
	for c := 0; c < 30; c++ {
		hi := 32768
		if c < 29 {
			hi = int(distBase[c+1]) - 1
		}
		for d := int(distBase[c]); d <= hi; d++ {
			distCode[d] = uint8(c)
		}
	}
}

func fixedLitLens() []uint8 {
	l := make([]uint8, 288)
	for i := range l {
		switch {
		case i < 144:
			l[i] = 8
		case i < 256:
			l[i] = 9
		case i < 280:
			l[i] = 7
		default:
			l[i] = 8
		}
	}
	return l
}

func fixedDistLens() []uint8 {
	l := make([]uint8, 32) // 30 and 31 are valid codes that decoders reject
	for i := range l {
		l[i] = 5
	}
	return l
}
