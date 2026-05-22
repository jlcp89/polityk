package macro

import (
	"encoding/csv"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
)

// ParseCSV reads a four-column CSV feed with the header row
//
//	code,observed_at,value,unit
//
// and returns one Indicator per data row with Source pre-filled. observed_at
// accepts YYYY-MM-DD (banguat / segeplan / minfin) and YYYY-MM (banguat
// monthly series and ine), the latter coerced to the first of the month so
// the DATE column always carries a real day.
//
// Empty rows, comment rows (#-prefixed first column), and rows whose value
// cell is empty or "n/a" are skipped silently -- the upstream feeds tend to
// pad ranges with empty cells for future quarters.
//
// Returns an error only for structural problems (missing header, wrong
// column count, unparseable value); per-row data drift surfaces as a
// per-row error wrapped with the source-relative line number.
func ParseCSV(r io.Reader, source string) ([]Indicator, error) {
	cr := csv.NewReader(r)
	cr.FieldsPerRecord = -1 // allow tolerance for trailing-comma quirks
	cr.TrimLeadingSpace = true

	rows, err := cr.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("csv: %w", err)
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("empty csv")
	}

	hdr := rows[0]
	if !headerMatches(hdr) {
		return nil, fmt.Errorf("unexpected header %v (want code,observed_at,value,unit)", hdr)
	}

	out := make([]Indicator, 0, len(rows)-1)
	for i, row := range rows[1:] {
		if len(row) == 0 {
			continue
		}
		first := strings.TrimSpace(row[0])
		if first == "" || strings.HasPrefix(first, "#") {
			continue
		}
		if len(row) < 3 {
			return nil, fmt.Errorf("row %d: want >=3 columns, got %d", i+2, len(row))
		}
		valStr := strings.TrimSpace(row[2])
		if valStr == "" || strings.EqualFold(valStr, "n/a") {
			continue
		}
		when, err := parseObservedAt(strings.TrimSpace(row[1]))
		if err != nil {
			return nil, fmt.Errorf("row %d: %w", i+2, err)
		}
		val, err := strconv.ParseFloat(valStr, 64)
		if err != nil {
			return nil, fmt.Errorf("row %d: parse value %q: %w", i+2, valStr, err)
		}
		unit := ""
		if len(row) >= 4 {
			unit = strings.TrimSpace(row[3])
		}
		out = append(out, Indicator{
			Source:     source,
			Code:       first,
			ObservedAt: when,
			Value:      val,
			Unit:       unit,
		})
	}
	return out, nil
}

func headerMatches(h []string) bool {
	if len(h) < 3 {
		return false
	}
	norm := func(s string) string {
		return strings.ToLower(strings.TrimSpace(s))
	}
	if norm(h[0]) != "code" || norm(h[1]) != "observed_at" || norm(h[2]) != "value" {
		return false
	}
	if len(h) >= 4 && norm(h[3]) != "unit" {
		return false
	}
	return true
}

// parseObservedAt accepts YYYY-MM-DD or YYYY-MM (coerced to the 1st).
func parseObservedAt(s string) (time.Time, error) {
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return t, nil
	}
	if t, err := time.Parse("2006-01", s); err == nil {
		return t, nil
	}
	return time.Time{}, fmt.Errorf("unparseable observed_at %q", s)
}
