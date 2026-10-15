package gb

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
)

// Palette is the on-screen colour for each of the four shades (lightest first).
var Palette = [4]color.RGBA{
	{0xE0, 0xF8, 0xD0, 0xFF},
	{0x88, 0xC0, 0x70, 0xFF},
	{0x34, 0x68, 0x56, 0xFF},
	{0x08, 0x18, 0x20, 0xFF},
}

// FrameRGBA writes the current frame as RGBA into dst (len >= 160*144*4).
func (g *GB) FrameRGBA(dst []byte) {
	for i, s := range g.PPU.front {
		c := Palette[s&3]
		dst[i*4], dst[i*4+1], dst[i*4+2], dst[i*4+3] = c.R, c.G, c.B, 0xFF
	}
}

// Image returns the frame as an image scaled by an integer factor (>=1).
func (g *GB) Image(scale int) *image.RGBA {
	if scale < 1 {
		scale = 1
	}
	img := image.NewRGBA(image.Rect(0, 0, ScreenW*scale, ScreenH*scale))
	for y := 0; y < ScreenH; y++ {
		for x := 0; x < ScreenW; x++ {
			c := Palette[g.PPU.front[y*ScreenW+x]&3]
			for dy := 0; dy < scale; dy++ {
				for dx := 0; dx < scale; dx++ {
					img.SetRGBA(x*scale+dx, y*scale+dy, c)
				}
			}
		}
	}
	return img
}

// PNG encodes the current frame.
func (g *GB) PNG(scale int) ([]byte, error) {
	var buf bytes.Buffer
	if err := png.Encode(&buf, g.Image(scale)); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// ASCII renders the frame as text using two characters per pixel row pair
// (half blocks), handy for terminals and golden tests.
func (g *GB) ASCII() string {
	const ramp = " .:#"
	var b bytes.Buffer
	for y := 0; y < ScreenH; y += 2 {
		for x := 0; x < ScreenW; x++ {
			a := g.PPU.front[y*ScreenW+x] & 3
			c := g.PPU.front[(y+1)*ScreenW+x] & 3
			b.WriteByte(ramp[(a+c+1)/2])
		}
		b.WriteByte('\n')
	}
	return b.String()
}
