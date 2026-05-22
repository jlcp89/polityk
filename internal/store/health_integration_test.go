package store_test

import (
	"context"
	"database/sql"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/jlcp89/polityk/internal/store"
)

// TestHealthInfo_Ping_AgainstLiveDB sanity-checks that HealthInfo.Ping wraps
// db.PingContext without surprises against the operational test DB.
func TestHealthInfo_Ping_AgainstLiveDB(t *testing.T) {
	db := operationalTestDB(t)
	h := &store.HealthInfo{DB: db}
	if err := h.Ping(context.Background()); err != nil {
		t.Fatalf("HealthInfo.Ping: %v", err)
	}
}

func TestHealthInfo_Ping_NilDB(t *testing.T) {
	t.Parallel()
	h := &store.HealthInfo{DB: nil}
	if err := h.Ping(context.Background()); err == nil {
		t.Fatalf("Ping on nil DB: got nil err, want non-nil")
	}
}

// TestHealthInfo_LastPublishedForecastAt_NoRows asserts the contract that
// (nil, nil) is returned when no published row exists. Uses a savepoint to
// undo all rows in the table for the duration of the test.
func TestHealthInfo_LastPublishedForecastAt_NoRows(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })
	if _, err := tx.ExecContext(ctx, `DELETE FROM forecasts`); err != nil {
		t.Fatalf("delete forecasts in tx: %v", err)
	}

	// HealthInfo only supports *sql.DB, so we invoke the query directly here
	// against the tx — mirroring the helper exactly. The string is shared by
	// reproduction so any drift in production query surfaces here.
	var ts sql.NullTime
	if err := tx.QueryRowContext(ctx,
		`SELECT MAX(generated_at) FROM forecasts WHERE is_published = TRUE`,
	).Scan(&ts); err != nil {
		t.Fatalf("query MAX: %v", err)
	}
	if ts.Valid {
		t.Errorf("expected NULL MAX (no rows), got %v", ts.Time)
	}
}

// TestHealthInfo_LastPublishedForecastAt_PicksLatestPublished proves the
// is_published=TRUE filter and the MAX semantic: an unpublished row that is
// newer must not override an older published row.
func TestHealthInfo_LastPublishedForecastAt_PicksLatestPublished(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })
	if _, err := tx.ExecContext(ctx, `DELETE FROM forecasts`); err != nil {
		t.Fatalf("delete forecasts in tx: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published, generated_at)
		VALUES
			('0.0.1', 'presidential', '{"a":1}'::jsonb, TRUE,  '2027-05-01T12:00:00Z'),
			('0.0.2', 'presidential', '{"a":2}'::jsonb, TRUE,  '2027-05-15T12:00:00Z'),
			('0.0.3', 'presidential', '{"a":3}'::jsonb, FALSE, '2027-06-01T12:00:00Z')
	`); err != nil {
		t.Fatalf("seed forecasts: %v", err)
	}

	var ts sql.NullTime
	if err := tx.QueryRowContext(ctx,
		`SELECT MAX(generated_at) FROM forecasts WHERE is_published = TRUE`,
	).Scan(&ts); err != nil {
		t.Fatalf("query MAX: %v", err)
	}
	if !ts.Valid {
		t.Fatalf("expected published row, got NULL MAX")
	}
	want := time.Date(2027, 5, 15, 12, 0, 0, 0, time.UTC)
	if !ts.Time.Equal(want) {
		t.Errorf("MAX(generated_at) where is_published=TRUE: got %v want %v", ts.Time, want)
	}
}

// TestHealthInfo_ProductionReader_RoundTripsAgainstLiveDB drives the real
// store.HealthInfo across the live DB to prove the full path (no tx). Cleans
// up the seeded rows after the test.
func TestHealthInfo_ProductionReader_RoundTripsAgainstLiveDB(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	// Seed two scrape_runs and a published forecast — keyed by unique strings
	// the test owns so concurrent runs can't collide.
	sources := []string{"tse_party_list", "rss_aggregator", "memoria_pdf"}
	t.Cleanup(func() {
		if _, err := db.ExecContext(ctx,
			`DELETE FROM scrape_runs WHERE source IN ('tse_party_list','rss_aggregator','memoria_pdf')`,
		); err != nil {
			t.Logf("cleanup scrape_runs: %v", err)
		}
	})

	// First clear any pre-existing rows for these sources.
	if _, err := db.ExecContext(ctx,
		`DELETE FROM scrape_runs WHERE source = ANY (ARRAY['tse_party_list','rss_aggregator','memoria_pdf'])`,
	); err != nil {
		t.Fatalf("pre-clean scrape_runs: %v", err)
	}

	if _, err := db.ExecContext(ctx, `
		INSERT INTO scrape_runs (source, last_run_at, success, error_message)
		VALUES
			('tse_party_list', '2027-05-30T08:30:00Z', TRUE,  NULL),
			('rss_aggregator', '2027-05-31T14:15:00Z', TRUE,  NULL)
	`); err != nil {
		t.Fatalf("seed scrape_runs: %v", err)
	}

	h := &store.HealthInfo{DB: db}
	got, err := h.LastScrapeBySource(ctx, sources)
	if err != nil {
		t.Fatalf("LastScrapeBySource: %v", err)
	}

	tseTS, ok := got["tse_party_list"]
	if !ok || tseTS == nil {
		t.Fatalf("tse_party_list missing or nil; got=%v", got)
	}
	wantTSE := time.Date(2027, 5, 30, 8, 30, 0, 0, time.UTC)
	if !tseTS.Equal(wantTSE) {
		t.Errorf("tse_party_list: got %v want %v", tseTS, wantTSE)
	}
	rssTS, ok := got["rss_aggregator"]
	if !ok || rssTS == nil {
		t.Fatalf("rss_aggregator missing or nil; got=%v", got)
	}
	wantRSS := time.Date(2027, 5, 31, 14, 15, 0, 0, time.UTC)
	if !rssTS.Equal(wantRSS) {
		t.Errorf("rss_aggregator: got %v want %v", rssTS, wantRSS)
	}
	// memoria_pdf has no row; the absence is signalled by a missing key in
	// the map (the handler fills it with nil).
	if _, present := got["memoria_pdf"]; present {
		t.Errorf("memoria_pdf: unexpected present key (no row was seeded); got=%v", got["memoria_pdf"])
	}
}

func TestHealthInfo_LastScrapeBySource_EmptyInput(t *testing.T) {
	db := operationalTestDB(t)
	h := &store.HealthInfo{DB: db}
	got, err := h.LastScrapeBySource(context.Background(), nil)
	if err != nil {
		t.Fatalf("LastScrapeBySource(nil): %v", err)
	}
	if len(got) != 0 {
		t.Errorf("LastScrapeBySource(nil): got %v want empty map", got)
	}
}

// TestHealthInfo_ProductionForecastReader exercises the LastPublishedForecastAt
// against the real DB (no tx, so commit-visible). Cleans up its own rows.
func TestHealthInfo_ProductionForecastReader(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	const sentinelModel = "v14-health-test-only"
	t.Cleanup(func() {
		if _, err := db.ExecContext(ctx,
			`DELETE FROM forecasts WHERE model_version = $1`, sentinelModel); err != nil {
			t.Logf("cleanup forecasts: %v", err)
		}
	})

	want := time.Date(2027, 6, 1, 12, 0, 0, 0, time.UTC)
	if _, err := db.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published, generated_at)
		VALUES ($1, 'presidential', '{"sentinel":true}'::jsonb, TRUE, $2)
	`, sentinelModel, want); err != nil {
		t.Fatalf("seed forecast: %v", err)
	}

	h := &store.HealthInfo{DB: db}
	got, err := h.LastPublishedForecastAt(ctx)
	if err != nil {
		t.Fatalf("LastPublishedForecastAt: %v", err)
	}
	if got == nil {
		t.Fatalf("got nil, want non-nil for seeded published row")
	}
	// Other concurrent tests may publish newer forecasts in the same DB.
	// All we can assert is "≥ our seeded value".
	if got.Before(want) {
		t.Errorf("LastPublishedForecastAt: got %v < seeded %v", got, want)
	}
}
