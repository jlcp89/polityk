package macro

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func readTestdata(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return string(b)
}

func TestParseCSV_BanguatFixture(t *testing.T) {
	t.Parallel()
	rows, err := ParseCSV(strings.NewReader(readTestdata(t, "banguat.csv")), SourceBanguat)
	if err != nil {
		t.Fatalf("ParseCSV: %v", err)
	}
	// 7 data rows (8 in file minus the empty-value row that is dropped silently
	// and the # comment row).
	if got, want := len(rows), 7; got != want {
		t.Fatalf("row count: got %d want %d", got, want)
	}

	first := rows[0]
	if first.Source != SourceBanguat {
		t.Errorf("source: got %q want %q", first.Source, SourceBanguat)
	}
	if first.Code != "gdp_yoy_growth" {
		t.Errorf("code: got %q want %q", first.Code, "gdp_yoy_growth")
	}
	if got, want := first.ObservedAt, time.Date(2024, 12, 31, 0, 0, 0, 0, time.UTC); !got.Equal(want) {
		t.Errorf("observed_at: got %v want %v", got, want)
	}
	if first.Value != 3.5 {
		t.Errorf("value: got %v want 3.5", first.Value)
	}
	if first.Unit != "percent" {
		t.Errorf("unit: got %q want %q", first.Unit, "percent")
	}

	// monthly form 2025-01 coerced to YYYY-MM-01
	var monthly *Indicator
	for i := range rows {
		if rows[i].Code == "inflation_yoy" && rows[i].ObservedAt.Month() == time.January {
			monthly = &rows[i]
			break
		}
	}
	if monthly == nil {
		t.Fatal("expected an inflation_yoy row in January 2025")
	}
	if got, want := monthly.ObservedAt, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC); !got.Equal(want) {
		t.Errorf("YYYY-MM coerced observed_at: got %v want %v", got, want)
	}
}

func TestParseCSV_AllFixtures_OnePerSource(t *testing.T) {
	t.Parallel()
	cases := []struct {
		fixture string
		source  string
		// codeMustInclude is one indicator per source that the fundamentals
		// layer (#31) consumes -- if the fixture loses it, the test fails.
		codeMustInclude string
	}{
		{"banguat.csv", SourceBanguat, "gdp_yoy_growth"},
		{"ine.csv", SourceINE, "homicide_rate_yoy"},
		{"segeplan.csv", SourceSEGEPLAN, "poverty_index"},
		{"minfin.csv", SourceMINFIN, "fiscal_balance_yoy"},
	}
	for _, tc := range cases {
		t.Run(tc.source, func(t *testing.T) {
			t.Parallel()
			rows, err := ParseCSV(strings.NewReader(readTestdata(t, tc.fixture)), tc.source)
			if err != nil {
				t.Fatalf("ParseCSV(%s): %v", tc.fixture, err)
			}
			if len(rows) == 0 {
				t.Fatalf("ParseCSV(%s): got 0 rows, want >=1", tc.fixture)
			}
			var found bool
			for _, r := range rows {
				if r.Source != tc.source {
					t.Errorf("row source: got %q want %q", r.Source, tc.source)
				}
				if r.Code == tc.codeMustInclude {
					found = true
				}
			}
			if !found {
				t.Errorf("fixture %s missing required code %q", tc.fixture, tc.codeMustInclude)
			}
		})
	}
}

func TestParseCSV_RejectsBadHeader(t *testing.T) {
	t.Parallel()
	bad := "indicator,date,amount\nfoo,2024-01-01,1\n"
	if _, err := ParseCSV(strings.NewReader(bad), SourceBanguat); err == nil {
		t.Fatal("expected error for bad header, got nil")
	}
}

func TestParseCSV_RejectsUnparseableValue(t *testing.T) {
	t.Parallel()
	bad := "code,observed_at,value,unit\nfoo,2024-01-01,bogus,percent\n"
	if _, err := ParseCSV(strings.NewReader(bad), SourceBanguat); err == nil {
		t.Fatal("expected error for unparseable value, got nil")
	}
}

func TestParseCSV_RejectsUnparseableDate(t *testing.T) {
	t.Parallel()
	bad := "code,observed_at,value,unit\nfoo,not-a-date,1.0,percent\n"
	if _, err := ParseCSV(strings.NewReader(bad), SourceBanguat); err == nil {
		t.Fatal("expected error for unparseable date, got nil")
	}
}

func TestParseCSV_SkipsEmptyAndComment(t *testing.T) {
	t.Parallel()
	src := "code,observed_at,value,unit\n# header comment\n\nfoo,2024-01-01,1.5,percent\n,,,\n"
	rows, err := ParseCSV(strings.NewReader(src), SourceBanguat)
	if err != nil {
		t.Fatalf("ParseCSV: %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("rows: got %d want 1", len(rows))
	}
	if rows[0].Code != "foo" {
		t.Errorf("code: got %q want %q", rows[0].Code, "foo")
	}
}

func TestIndicator_Validate(t *testing.T) {
	t.Parallel()
	when := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	tests := []struct {
		name    string
		in      Indicator
		wantErr bool
	}{
		{"ok_banguat", Indicator{Source: SourceBanguat, Code: "x", ObservedAt: when}, false},
		{"ok_ine", Indicator{Source: SourceINE, Code: "x", ObservedAt: when}, false},
		{"ok_segeplan", Indicator{Source: SourceSEGEPLAN, Code: "x", ObservedAt: when}, false},
		{"ok_minfin", Indicator{Source: SourceMINFIN, Code: "x", ObservedAt: when}, false},
		{"bad_source", Indicator{Source: "twitter", Code: "x", ObservedAt: when}, true},
		{"empty_code", Indicator{Source: SourceBanguat, Code: "", ObservedAt: when}, true},
		{"zero_date", Indicator{Source: SourceBanguat, Code: "x", ObservedAt: time.Time{}}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			err := tt.in.Validate()
			if tt.wantErr && err == nil {
				t.Errorf("expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Errorf("expected no error, got %v", err)
			}
		})
	}
}
