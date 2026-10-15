package main

import (
	"errors"
	"flag"
	"fmt"
	"mime"
	"net"
	"net/http"
	"strconv"

	"dotmatrix/web"
)

// cmdServe serves the embedded browser player. It binds to loopback by
// default: the page needs nothing from the network and exposes no files.
func cmdServe(args []string) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	addr := fs.String("addr", "127.0.0.1:8080", "listen address")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if len(pos) != 0 {
		return errors.New("serve takes no positional arguments")
	}
	_ = mime.AddExtensionType(".wasm", "application/wasm")
	_ = mime.AddExtensionType(".js", "text/javascript")
	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		return err
	}
	fmt.Printf("Dotmatrix player: http://%s/  (Ctrl-C to stop)\n", ln.Addr())
	h := http.FileServerFS(web.FS)
	return http.Serve(ln, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache")
		if r.URL.Path == "/dotmatrix.wasm" { // stored gzipped in the binary; browsers inflate it transparently
			b, err := web.FS.ReadFile("dotmatrix.wasm.gz")
			if err != nil {
				http.Error(w, "wasm core missing (run web/build.sh)", http.StatusInternalServerError)
				return
			}
			w.Header().Set("Content-Type", "application/wasm")
			w.Header().Set("Content-Encoding", "gzip")
			w.Header().Set("Content-Length", strconv.Itoa(len(b)))
			if r.Method != http.MethodHead {
				w.Write(b)
			}
			return
		}
		h.ServeHTTP(w, r)
	}))
}
