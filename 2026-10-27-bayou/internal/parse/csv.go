package parse

import (
	"encoding/csv"
	"fmt"
	"io"
	"strings"

	"bayou/internal/bn"
)

// Dataset is a table of observations. Cols[i] is the variable id of column i;
// Rows[r][i] is the state index, or Missing (-1).
type Dataset struct {
	Cols []int
	Rows [][]int
}

// Missing marks an unobserved cell.
const Missing = -1

var missingTokens = map[string]bool{"": true, "?": true, "na": true, "nan": true, "null": true, "none": true}

// ReadCSV reads a dataset for net. The header names the variables (a subset of
// the network is fine: the others are latent). Cells "", "?", "NA" are missing.
func ReadCSV(net *bn.Network, r io.Reader) (*Dataset, error) {
	cr := csv.NewReader(r)
	cr.FieldsPerRecord = -1
	cr.TrimLeadingSpace = true
	hdr, err := cr.Read()
	if err == io.EOF {
		return nil, fmt.Errorf("csv is empty (expected a header row of variable names)")
	}
	if err != nil {
		return nil, fmt.Errorf("csv: %v", err)
	}
	ds := &Dataset{}
	seen := map[int]bool{}
	for i, h := range hdr {
		h = strings.TrimSpace(h)
		v, ok := net.ID(h)
		if !ok {
			return nil, fmt.Errorf("csv column %d: %q is not a variable of the network", i+1, h)
		}
		if seen[v] {
			return nil, fmt.Errorf("csv column %d: %q appears twice in the header", i+1, h)
		}
		seen[v] = true
		ds.Cols = append(ds.Cols, v)
	}
	for line := 2; ; line++ {
		rec, err := cr.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("csv line %d: %v", line, err)
		}
		if len(rec) == 1 && strings.TrimSpace(rec[0]) == "" {
			continue // blank line
		}
		if len(rec) != len(ds.Cols) {
			return nil, fmt.Errorf("csv line %d: %d fields, header has %d", line, len(rec), len(ds.Cols))
		}
		row := make([]int, len(rec))
		for i, cell := range rec {
			cell = strings.TrimSpace(cell)
			s, ok := net.StateID(ds.Cols[i], cell)
			if !ok && missingTokens[strings.ToLower(cell)] { // a real state named "none"/"NA" wins over the marker
				row[i] = Missing
				continue
			}
			if !ok {
				return nil, fmt.Errorf("csv line %d, column %s: %q is not a state (states: %s)", line, net.Vars[ds.Cols[i]].Name, cell, strings.Join(net.Vars[ds.Cols[i]].States, ", "))
			}
			row[i] = s
		}
		ds.Rows = append(ds.Rows, row)
	}
	return ds, nil
}

// WriteCSV writes the dataset with state names.
func WriteCSV(w io.Writer, net *bn.Network, ds *Dataset) error {
	cw := csv.NewWriter(w)
	hdr := make([]string, len(ds.Cols))
	for i, v := range ds.Cols {
		hdr[i] = net.Vars[v].Name
	}
	if err := cw.Write(hdr); err != nil {
		return err
	}
	marker := missingMarker(net, ds)
	for _, row := range ds.Rows {
		rec := make([]string, len(row))
		for i, s := range row {
			if s != Missing {
				rec[i] = net.Vars[ds.Cols[i]].States[s]
			} else {
				rec[i] = marker
			}
		}
		if err := cw.Write(rec); err != nil {
			return err
		}
	}
	cw.Flush()
	return cw.Error()
}

// missingMarker picks a cell text for "missing" that no column's state uses.
func missingMarker(net *bn.Network, ds *Dataset) string {
	for _, m := range []string{"?", "NA", "<missing>"} {
		clash := false
		for _, v := range ds.Cols {
			if _, ok := net.StateID(v, m); ok {
				clash = true
			}
		}
		if !clash {
			return m
		}
	}
	return "<missing>"
}
