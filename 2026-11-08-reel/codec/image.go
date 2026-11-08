package codec

import "image"
import "image/color"

// ToImage converts the visible area of a frame to RGB (BT.601 limited range).
func ToImage(f *Frame) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, f.Width, f.Height))
	for y := 0; y < f.Height; y++ {
		for x := 0; x < f.Width; x++ {
			Y := float64(f.Y.Pix[f.Y.idx(x, y)]) - 16
			U := float64(f.U.Pix[f.U.idx(x/2, y/2)]) - 128
			V := float64(f.V.Pix[f.V.idx(x/2, y/2)]) - 128
			r := 1.164*Y + 1.596*V
			g := 1.164*Y - 0.392*U - 0.813*V
			b := 1.164*Y + 2.017*U
			img.SetRGBA(x, y, color.RGBA{clip255(int(r + 0.5)), clip255(int(g + 0.5)), clip255(int(b + 0.5)), 255})
		}
	}
	return img
}

// DiffImage renders |a-b| on luma, amplified by gain, as greyscale.
func DiffImage(a, b *Frame, gain int) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, a.Width, a.Height))
	for y := 0; y < a.Height; y++ {
		for x := 0; x < a.Width; x++ {
			d := iabs(int(a.Y.Pix[a.Y.idx(x, y)])-int(b.Y.Pix[b.Y.idx(x, y)])) * gain
			v := clip255(255 - d)
			img.SetRGBA(x, y, color.RGBA{v, v, v, 255})
		}
	}
	return img
}
