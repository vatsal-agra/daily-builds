package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync"
	"time"

	"keyhole/tls13"
)

func cmdInspect(args []string) error {
	fs := newFlags("inspect")
	listen := fs.String("listen", "127.0.0.1:9443", "address the proxy listens on")
	upstream := fs.String("upstream", "", "host:port of the real TLS server (required)")
	keylog := fs.String("keylog", "", "NSS key log file written by the client or server (required)")
	data := fs.Int("data", 0, "show up to this many bytes of decrypted application data")
	html := fs.String("html", "", "also write a self-contained HTML timeline of every session here on exit")
	if err := parse(fs, args); err != nil {
		return err
	}
	if *upstream == "" || *keylog == "" {
		return errors.New("-upstream and -keylog are required")
	}
	l, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	fmt.Printf("keyhole inspect: %s → %s, secrets from %s\n", l.Addr(), *upstream, *keylog)
	var mu sync.Mutex
	var sessions [][]tls13.InspectEvent
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt)
	go func() { <-stop; l.Close() }()
	var wg sync.WaitGroup
	n := 0
	for {
		cli, err := l.Accept()
		if err != nil {
			break
		}
		n++
		id := n
		wg.Add(1)
		go func() {
			defer wg.Done()
			var evs []tls13.InspectEvent
			var emu sync.Mutex
			in := tls13.NewInspector(func() tls13.KeyLog { return tls13.ReadKeyLogFile(*keylog) }, func(e tls13.InspectEvent) {
				emu.Lock()
				evs = append(evs, e)
				emu.Unlock()
				printInspectEvent(id, e)
			})
			in.ShowData = *data
			proxyConn(cli, *upstream, in)
			in.Close()
			mu.Lock()
			emu.Lock()
			sessions = append(sessions, evs)
			emu.Unlock()
			mu.Unlock()
		}()
	}
	wg.Wait()
	if *html != "" {
		mu.Lock()
		defer mu.Unlock()
		if err := os.WriteFile(*html, []byte(renderTimeline(sessions)), 0o644); err != nil {
			return err
		}
		fmt.Printf("wrote %s (%d session(s))\n", *html, len(sessions))
	}
	return nil
}

func proxyConn(cli net.Conn, upstream string, in *tls13.Inspector) {
	defer cli.Close()
	srv, err := net.DialTimeout("tcp", upstream, 10*time.Second)
	if err != nil {
		fmt.Fprintf(os.Stderr, "upstream: %v\n", err)
		return
	}
	defer srv.Close()
	done := make(chan struct{}, 2)
	pipe := func(from, to net.Conn, fromClient bool) {
		buf := make([]byte, 32<<10)
		for {
			n, err := from.Read(buf)
			if n > 0 {
				if _, werr := to.Write(buf[:n]); werr != nil {
					break
				}
				in.Feed(fromClient, buf[:n])
			}
			if err != nil {
				break
			}
		}
		if tc, ok := to.(*net.TCPConn); ok {
			tc.CloseWrite()
		}
		done <- struct{}{}
	}
	go pipe(cli, srv, true)
	go pipe(srv, cli, false)
	tick := time.NewTicker(50 * time.Millisecond) // retry records that were waiting for key log lines
	defer tick.Stop()
	finished := 0
	for finished < 2 {
		select {
		case <-done:
			finished++
		case <-tick.C:
			in.Poll()
		}
	}
	time.Sleep(100 * time.Millisecond)
	in.Poll()
	_ = io.EOF
}

func printInspectEvent(id int, e tls13.InspectEvent) {
	arrow := paint("36", "C→S")
	if !e.FromCli {
		arrow = paint("35", "S→C")
	}
	line := fmt.Sprintf("[#%d] %s %-9s %s", id, arrow, e.Kind, paint("1", e.Summary))
	if e.Detail != "" {
		line += "\n         " + strings.ReplaceAll(strings.TrimRight(e.Detail, "\n"), "\n", "\n         ")
	}
	fmt.Println(line)
}
