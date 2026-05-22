package macro

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// openTestDB mirrors tse / rss / store: gated on POLITYK_TEST_DATABASE_URL
// so unit-only `go test ./...` keeps working without Postgres. Caller is
// expected to have migrations 0001 + 0005 (scrape_runs) + 0007 applied.
func openTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping macro integration test")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := db.PingContext(context.Background()); err != nil {
		t.Skipf("DB not reachable: %v", err)
	}
	return db
}

func truncateMacroTables(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	for _, stmt := range []string{
		"TRUNCATE TABLE macro_indicators RESTART IDENTITY",
		"DELETE FROM scrape_runs WHERE source IN ('banguat','ine','segeplan','minfin')",
	} {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			t.Fatalf("truncate (%s): %v", stmt, err)
		}
	}
}

// TestUpsert_IdempotentAndUniqueViolation_Integration writes the same row
// twice and asserts the UNIQUE(source, code, observed_at) constraint
// silently de-duplicates the second insert (matching the issue body's
// "Idempotent: duplicate ... rejected" criterion).
func TestUpsert_IdempotentAndUniqueViolation_Integration(t *testing.T) {
	db := openTestDB(t)
	truncateMacroTables(t, db)

	rows := []Indicator{
		{
			Source:     SourceBanguat,
			Code:       "gdp_yoy_growth",
			ObservedAt: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC),
			Value:      3.5,
			Unit:       "percent",
		},
	}
	first, err := Upsert(context.Background(), db, rows)
	if err != nil {
		t.Fatalf("Upsert (first): %v", err)
	}
	if first != 1 {
		t.Errorf("first Upsert inserted: got %d want 1", first)
	}
	second, err := Upsert(context.Background(), db, rows)
	if err != nil {
		t.Fatalf("Upsert (second): %v", err)
	}
	if second != 0 {
		t.Errorf("second Upsert inserted: got %d want 0 (ON CONFLICT DO NOTHING)", second)
	}

	var total int
	if err := db.QueryRow(`SELECT COUNT(*) FROM macro_indicators`).Scan(&total); err != nil {
		t.Fatalf("count: %v", err)
	}
	if total != 1 {
		t.Errorf("macro_indicators total: got %d want 1", total)
	}
}

// TestUpsert_RejectsInvalidSource_Integration pins migration 0007's CHECK
// constraint: a source outside the locked set ('banguat','ine','segeplan',
// 'minfin') must be rejected at the schema layer. (Indicator.Validate
// catches it earlier in production code; this test bypasses Validate and
// drives the DB directly via raw SQL to prove the schema also enforces it.)
func TestUpsert_RejectsInvalidSource_Integration(t *testing.T) {
	db := openTestDB(t)
	truncateMacroTables(t, db)

	_, err := db.ExecContext(context.Background(), `
		INSERT INTO macro_indicators (source, code, observed_at, value, unit)
		VALUES ('twitter', 'x', '2025-01-01', 1.0, 'percent')
	`)
	if err == nil {
		t.Fatal("expected CHECK violation for source='twitter', got nil")
	}
}

// TestRun_EachSourceRoundTrips_Integration runs all four scrapers against
// httptest fixture servers and asserts each one wrote to macro_indicators
// and stamped scrape_runs with the correct source.
func TestRun_EachSourceRoundTrips_Integration(t *testing.T) {
	db := openTestDB(t)
	truncateMacroTables(t, db)

	cases := []struct {
		ctor    func() *Client
		fixture string
		source  string
	}{
		{NewBanguatClient, "banguat.csv", SourceBanguat},
		{NewINEClient, "ine.csv", SourceINE},
		{NewSEGEPLANClient, "segeplan.csv", SourceSEGEPLAN},
		{NewMINFINClient, "minfin.csv", SourceMINFIN},
	}
	for _, tc := range cases {
		srv, _, _ := newFixtureServer(t, tc.fixture)
		c := tc.ctor()
		c.FeedURL = srv.URL
		c.HTTPClient = srv.Client()

		stats, err := c.Run(context.Background(), db)
		if err != nil {
			t.Fatalf("%s Run: %v", tc.source, err)
		}
		if stats.Inserted == 0 {
			t.Errorf("%s: Inserted got 0, want >=1", tc.source)
		}

		var count int
		if err := db.QueryRow(
			`SELECT COUNT(*) FROM macro_indicators WHERE source = $1`, tc.source,
		).Scan(&count); err != nil {
			t.Fatalf("%s count: %v", tc.source, err)
		}
		if count == 0 {
			t.Errorf("%s: macro_indicators count got 0, want >=1", tc.source)
		}

		var success bool
		var lastRunAt time.Time
		err = db.QueryRow(
			`SELECT success, last_run_at FROM scrape_runs WHERE source = $1`, tc.source,
		).Scan(&success, &lastRunAt)
		if errors.Is(err, sql.ErrNoRows) {
			t.Errorf("%s: scrape_runs row missing", tc.source)
			continue
		}
		if err != nil {
			t.Fatalf("%s scrape_runs query: %v", tc.source, err)
		}
		if !success {
			t.Errorf("%s: scrape_runs.success got false want true", tc.source)
		}
		if time.Since(lastRunAt) > 30*time.Second {
			t.Errorf("%s: scrape_runs.last_run_at stale: %v", tc.source, lastRunAt)
		}
	}
}

// TestRun_StampsFailureOnHTTPError_Integration pins the failure-path
// scrape_runs contract: a failed fetch must still produce a scrape_runs row
// with success=false so /v1/health can surface the dead source.
func TestRun_StampsFailureOnHTTPError_Integration(t *testing.T) {
	db := openTestDB(t)
	truncateMacroTables(t, db)

	// Point at a guaranteed-to-fail address (closed loopback port). The
	// DialContext error path covers connection refused without depending on
	// upstream behavior.
	c := NewBanguatClient()
	c.FeedURL = "http://127.0.0.1:1/never-listens.csv"

	if _, err := c.Run(context.Background(), db); err == nil {
		t.Fatal("expected error for unreachable feed, got nil")
	}

	var success bool
	var errMsg sql.NullString
	qerr := db.QueryRow(
		`SELECT success, error_message FROM scrape_runs WHERE source = $1`, SourceBanguat,
	).Scan(&success, &errMsg)
	if errors.Is(qerr, sql.ErrNoRows) {
		t.Fatal("scrape_runs row not stamped on failure")
	}
	if qerr != nil {
		t.Fatalf("scrape_runs query: %v", qerr)
	}
	if success {
		t.Error("scrape_runs.success: got true want false")
	}
	if !errMsg.Valid || errMsg.String == "" {
		t.Error("scrape_runs.error_message: got empty want non-empty")
	}
}
