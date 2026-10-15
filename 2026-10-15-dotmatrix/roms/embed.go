// Package roms embeds the demo/test ROM sources so the web player and the
// CLI can offer them without touching the filesystem.
package roms

import "embed"

//go:embed *.asm *.inc
var FS embed.FS
