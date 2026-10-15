// Package web embeds the browser player so the CLI can serve it.
package web

import "embed"

//go:embed index.html wasm_exec.js dotmatrix.wasm.gz
var FS embed.FS
