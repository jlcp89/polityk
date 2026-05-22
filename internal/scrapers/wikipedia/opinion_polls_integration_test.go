package wikipedia

import (
	"bytes"
	"context"
	"database/sql"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// scraperTestDB is the same pattern used by polls_integration_test.go:
// skip cleanly when POLITYK_TEST_DATABASE_URL is empty so the unit-only
// `go test ./...` workflow keeps working without Postgres.
func scraperTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping Wikipedia scraper integration test")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("ping: %v", err)
	}
	return db
}

// fixtureServer serves the testdata fixture at /api/rest_v1/page/html/<title>.
func fixtureServer(t *testing.T) *httptest.Server {
	t.Helper()
	bs, err := os.ReadFile("testdata/opinion_polls_2023.html")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/api/rest_v1/page/html/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = io.Copy(w, bytes.NewReader(bs))
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func TestRun_HappyPath_InsertsPollsAndStampsScrapeRuns(t *testing.T) {
	db := scraperTestDB(t)
	ctx := context.Background()

	// Seed candidates that match the fixture column headers; rolled back
	// via a transaction is awkward because the scraper opens fresh DB
	// connections — clean up by name after the test.
	candidateNames := []string{"Sandra Torres", "Bernardo Arévalo", "Edmond Mulet", "Zury Ríos"}
	candidateIDs := make(map[string]int64, len(candidateNames))
	for _, n := range candidateNames {
		var id int64
		if err := db.QueryRowContext(ctx,
			`INSERT INTO candidates (full_name) VALUES ($1) RETURNING candidate_id`, n,
		).Scan(&id); err != nil {
			t.Fatalf("seed candidate %q: %v", n, err)
		}
		candidateIDs[n] = id
	}
	t.Cleanup(func() { cleanupTestRows(t, db, candidateIDs) })

	srv := fixtureServer(t)
	logger, audit := newAuditLogger()

	scraper := &Scraper{
		HTTPClient: srv.Client(),
		BaseURL:    srv.URL + "/api/rest_v1/page/html",
		PageTitle:  "Opinion_polling_for_the_2023_Guatemalan_general_election",
		Logger:     logger,
	}
	stats, err := scraper.Run(ctx, db)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}

	// 5 fixture rows, 1 pollster ("Random Unknown Pollster") unresolved.
	if got, want := stats.PollsInserted, 4; got != want {
		t.Errorf("polls_inserted: got %d want %d", got, want)
	}
	if got, want := stats.UnresolvedPollsterRows, 1; got != want {
		t.Errorf("unresolved_pollster_rows: got %d want %d", got, want)
	}
	if got, want := stats.ResponsesInserted, 16; got != want { // 4 polls * 4 candidates each
		t.Errorf("responses_inserted: got %d want %d", got, want)
	}

	// WARN log emitted for "Random Unknown Pollster".
	if !audit.contains("Random Unknown Pollster") {
		t.Errorf("expected WARN log for unresolved pollster; got %q", audit.buf.String())
	}

	// scrape_runs row exists with source=wikipedia_polls, success=true.
	var (
		lastRun time.Time
		ok      bool
		msg     sql.NullString
	)
	if err := db.QueryRowContext(ctx,
		`SELECT last_run_at, success, error_message FROM scrape_runs WHERE source=$1`,
		SourceTag,
	).Scan(&lastRun, &ok, &msg); err != nil {
		t.Fatalf("scrape_runs lookup: %v", err)
	}
	if !ok {
		t.Errorf("scrape_runs.success should be true on happy path; msg=%v", msg)
	}
	if time.Since(lastRun) > time.Minute {
		t.Errorf("scrape_runs.last_run_at too old: %v", lastRun)
	}
}

func TestRun_Idempotent_DuplicateRunInsertsNothing(t *testing.T) {
	db := scraperTestDB(t)
	ctx := context.Background()

	candidateNames := []string{"Sandra Torres", "Bernardo Arévalo", "Edmond Mulet", "Zury Ríos"}
	candidateIDs := make(map[string]int64, len(candidateNames))
	for _, n := range candidateNames {
		var id int64
		if err := db.QueryRowContext(ctx,
			`INSERT INTO candidates (full_name) VALUES ($1) RETURNING candidate_id`, n,
		).Scan(&id); err != nil {
			t.Fatalf("seed candidate %q: %v", n, err)
		}
		candidateIDs[n] = id
	}
	t.Cleanup(func() { cleanupTestRows(t, db, candidateIDs) })

	srv := fixtureServer(t)
	scraper := &Scraper{
		HTTPClient: srv.Client(),
		BaseURL:    srv.URL + "/api/rest_v1/page/html",
		PageTitle:  "Opinion_polling_for_the_2023_Guatemalan_general_election",
		Logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	if _, err := scraper.Run(ctx, db); err != nil {
		t.Fatalf("first Run: %v", err)
	}
	stats, err := scraper.Run(ctx, db)
	if err != nil {
		t.Fatalf("second Run: %v", err)
	}
	if stats.PollsInserted != 0 {
		t.Errorf("re-run polls_inserted: got %d want 0", stats.PollsInserted)
	}
	if stats.PollsDuplicate != 4 {
		t.Errorf("re-run polls_duplicate: got %d want 4", stats.PollsDuplicate)
	}
}

func TestRun_FailedFetch_StampsScrapeRunsAsFailed(t *testing.T) {
	db := scraperTestDB(t)
	ctx := context.Background()

	// Server that returns 500 for every request.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "boom", http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)

	scraper := &Scraper{
		HTTPClient: srv.Client(),
		BaseURL:    srv.URL + "/api/rest_v1/page/html",
		PageTitle:  "Opinion_polling_for_the_2023_Guatemalan_general_election",
		Logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	if _, err := scraper.Run(ctx, db); err == nil {
		t.Fatalf("expected non-nil error on 500; got nil")
	}

	var (
		success bool
		msg     sql.NullString
	)
	if err := db.QueryRowContext(ctx,
		`SELECT success, error_message FROM scrape_runs WHERE source=$1`,
		SourceTag,
	).Scan(&success, &msg); err != nil {
		t.Fatalf("scrape_runs lookup: %v", err)
	}
	if success {
		t.Errorf("scrape_runs.success should be false on fetch failure")
	}
	if !msg.Valid || msg.String == "" {
		t.Errorf("scrape_runs.error_message should be populated; got %v", msg)
	}
}

// cleanupTestRows removes polls + poll_responses keyed by source_url derived
// from PageTitle plus the seeded candidates. Done in t.Cleanup so a panic
// upstream doesn't leak rows into the shared CI database.
func cleanupTestRows(t *testing.T, db *sql.DB, candidateIDs map[string]int64) {
	t.Helper()
	ctx := context.Background()
	const srcURL = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_2023_Guatemalan_general_election"
	if _, err := db.ExecContext(ctx,
		`DELETE FROM poll_responses WHERE poll_id IN (SELECT poll_id FROM polls WHERE source_url=$1)`,
		srcURL,
	); err != nil {
		t.Logf("cleanup poll_responses: %v", err)
	}
	if _, err := db.ExecContext(ctx, `DELETE FROM polls WHERE source_url=$1`, srcURL); err != nil {
		t.Logf("cleanup polls: %v", err)
	}
	for _, id := range candidateIDs {
		if _, err := db.ExecContext(ctx, `DELETE FROM candidates WHERE candidate_id=$1`, id); err != nil {
			t.Logf("cleanup candidate %d: %v", id, err)
		}
	}
	if _, err := db.ExecContext(ctx, `DELETE FROM scrape_runs WHERE source=$1`, SourceTag); err != nil {
		t.Logf("cleanup scrape_runs: %v", err)
	}
}

// auditLogger wraps a slog Logger pointed at an in-memory buffer so the
// test can assert on WARN-level lines without snooping on global state.
type auditLogger struct {
	buf bytes.Buffer
}

func (a *auditLogger) contains(substr string) bool {
	return bytes.Contains(a.buf.Bytes(), []byte(substr))
}

func newAuditLogger() (*slog.Logger, *auditLogger) {
	a := &auditLogger{}
	h := slog.NewTextHandler(&a.buf, &slog.HandlerOptions{Level: slog.LevelWarn})
	return slog.New(h), a
}
