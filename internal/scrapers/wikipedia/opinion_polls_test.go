package wikipedia

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestParseWikitable_FixtureRowCount is the issue-#17 acceptance gate:
// "Fixture-driven test on the 2023 article wikitable matches expected row
// count." The fixture has 5 data rows; every row has a recognisable date
// range and at least one candidate column, so the parser must return all 5.
func TestParseWikitable_FixtureRowCount(t *testing.T) {
	rows := loadFixtureRows(t)
	if got, want := len(rows), 5; got != want {
		t.Fatalf("row count: got %d want %d", got, want)
	}
}

func TestParseWikitable_FieldsExtracted(t *testing.T) {
	rows := loadFixtureRows(t)
	first := rows[0]
	if first.Pollster != "CID Gallup" {
		t.Errorf("pollster: got %q want %q", first.Pollster, "CID Gallup")
	}
	wantStart, _ := time.Parse("2006-01-02", "2023-05-01")
	wantEnd, _ := time.Parse("2006-01-02", "2023-05-10")
	if !first.FieldStart.Equal(wantStart) {
		t.Errorf("field_start: got %v want %v", first.FieldStart, wantStart)
	}
	if !first.FieldEnd.Equal(wantEnd) {
		t.Errorf("field_end: got %v want %v", first.FieldEnd, wantEnd)
	}
	if !first.SampleSize.Valid || first.SampleSize.Int32 != 1205 {
		t.Errorf("sample_size: got %v want 1205", first.SampleSize)
	}
	if !first.MarginOfError.Valid || diff(first.MarginOfError.Float64, 0.028) > 1e-9 {
		t.Errorf("margin_of_error: got %v want ~0.028", first.MarginOfError)
	}
	if got, want := first.CandidateShare["Sandra Torres"], 0.224; diff(got, want) > 1e-9 {
		t.Errorf("Torres share: got %v want %v", got, want)
	}
	if got, want := first.CandidateShare["Bernardo Arévalo"], 0.028; diff(got, want) > 1e-9 {
		t.Errorf("Arévalo share: got %v want %v", got, want)
	}
}

func TestParseWikitable_MissingSampleSizeFallsBackToNull(t *testing.T) {
	rows := loadFixtureRows(t)
	var fld *PollRow
	for i, r := range rows {
		if r.Pollster == "Fundación Libertad y Desarrollo" {
			fld = &rows[i]
			break
		}
	}
	if fld == nil {
		t.Fatalf("missing FLD row in fixture")
	}
	if fld.SampleSize.Valid {
		t.Errorf("sample_size should be NULL when cell is empty; got %v", fld.SampleSize.Int32)
	}
}

func TestParseDateRange_Cases(t *testing.T) {
	cases := []struct {
		in           string
		wantStart    string
		wantEnd      string
		wantOK       bool
	}{
		{"1–10 May 2023", "2023-05-01", "2023-05-10", true},
		{"1-10 May 2023", "2023-05-01", "2023-05-10", true},
		{"30 April – 2 May 2023", "2023-04-30", "2023-05-02", true},
		{"12 June 2023", "2023-06-12", "2023-06-12", true},
		{"sometime in the future", "", "", false},
	}
	for _, tt := range cases {
		t.Run(tt.in, func(t *testing.T) {
			s, e, ok := parseDateRange(tt.in)
			if ok != tt.wantOK {
				t.Fatalf("parseDateRange ok: got %v want %v", ok, tt.wantOK)
			}
			if !ok {
				return
			}
			if got := s.Format("2006-01-02"); got != tt.wantStart {
				t.Errorf("start: got %q want %q", got, tt.wantStart)
			}
			if got := e.Format("2006-01-02"); got != tt.wantEnd {
				t.Errorf("end: got %q want %q", got, tt.wantEnd)
			}
		})
	}
}

func TestParsePercent_Cases(t *testing.T) {
	cases := []struct {
		in        string
		wantValue float64
		wantOK    bool
	}{
		{"22.4%", 0.224, true},
		{"3%", 0.03, true},
		{"3.0%", 0.03, true},
		{"-", 0, false},
		{"", 0, false},
		{"110%", 0, false},
	}
	for _, tt := range cases {
		t.Run(tt.in, func(t *testing.T) {
			v, ok := parsePercent(tt.in)
			if ok != tt.wantOK {
				t.Fatalf("ok: got %v want %v", ok, tt.wantOK)
			}
			if ok && diff(v, tt.wantValue) > 1e-9 {
				t.Errorf("value: got %v want %v", v, tt.wantValue)
			}
		})
	}
}

func TestIsCandidateHeader_SkipsMetadata(t *testing.T) {
	skip := []string{"Polling firm", "Fieldwork date", "Sample size", "Margin of error", "Lead", ""}
	for _, h := range skip {
		if isCandidateHeader(h) {
			t.Errorf("header %q should not be a candidate column", h)
		}
	}
	keep := []string{"Sandra Torres", "Bernardo Arévalo", "Zury Ríos"}
	for _, h := range keep {
		if !isCandidateHeader(h) {
			t.Errorf("header %q should be a candidate column", h)
		}
	}
}

func loadFixtureRows(t *testing.T) []PollRow {
	t.Helper()
	path := filepath.Join("testdata", "opinion_polls_2023.html")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open fixture: %v", err)
	}
	defer f.Close()
	rows, err := ParseWikitable(f)
	if err != nil {
		t.Fatalf("ParseWikitable: %v", err)
	}
	return rows
}

func diff(a, b float64) float64 {
	if a > b {
		return a - b
	}
	return b - a
}

// TestSourceTag_Stable is a guard against accidental renames; the scrape_runs
// row + /v1/health (#14) both key off this constant.
func TestSourceTag_Stable(t *testing.T) {
	if SourceTag != "wikipedia_polls" {
		t.Errorf("SourceTag drifted: got %q want %q", SourceTag, "wikipedia_polls")
	}
	if !strings.Contains(DefaultBaseURL, "/api/rest_v1/page/html") {
		t.Errorf("DefaultBaseURL must hit the REST API: got %q", DefaultBaseURL)
	}
}
