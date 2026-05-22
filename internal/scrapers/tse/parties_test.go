package tse

import (
	"context"
	"database/sql"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

const fixturePath = "testdata/parties.html"

func readFixture(t *testing.T) []byte {
	t.Helper()
	b, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	return b
}

func TestParseParties_FixtureCounts(t *testing.T) {
	t.Parallel()
	parsed, err := parseParties(strings.NewReader(string(readFixture(t))))
	if err != nil {
		t.Fatalf("parseParties: %v", err)
	}
	if got, want := len(parsed), 39; got != want {
		t.Fatalf("total parties: got %d want %d", got, want)
	}

	counts := map[PartyStatus]int{}
	for _, p := range parsed {
		counts[p.Status]++
	}
	if got, want := counts[StatusActive], 28; got != want {
		t.Errorf("active parties: got %d want %d", got, want)
	}
	if got, want := counts[StatusCancelled], 10; got != want {
		t.Errorf("cancelled parties: got %d want %d", got, want)
	}
	if got, want := counts[StatusCancelledUnderAppeal], 1; got != want {
		t.Errorf("cancelled_under_appeal parties: got %d want %d", got, want)
	}
	// Acceptance criterion phrasing: "28 active + 11 cancelled parties exactly".
	// "cancelled" here counts both ENUM values that aren't active.
	nonActive := counts[StatusCancelled] + counts[StatusCancelledUnderAppeal]
	if got, want := nonActive, 11; got != want {
		t.Errorf("non-active parties: got %d want %d", got, want)
	}
}

func TestParseParties_SemillaCancelledUnderAppeal(t *testing.T) {
	t.Parallel()
	parsed, err := parseParties(strings.NewReader(string(readFixture(t))))
	if err != nil {
		t.Fatalf("parseParties: %v", err)
	}
	var semilla *ParsedParty
	for i := range parsed {
		if parsed[i].TSECode == "SEMILLA" {
			semilla = &parsed[i]
			break
		}
	}
	if semilla == nil {
		t.Fatal("Movimiento Semilla row missing from fixture")
	}
	if semilla.Status != StatusCancelledUnderAppeal {
		t.Errorf("Semilla status: got %q want %q", semilla.Status, StatusCancelledUnderAppeal)
	}
	if !strings.Contains(semilla.Name, "Semilla") {
		t.Errorf("Semilla name: got %q want substring %q", semilla.Name, "Semilla")
	}
}

func TestParseParties_Aliases(t *testing.T) {
	t.Parallel()
	parsed, err := parseParties(strings.NewReader(string(readFixture(t))))
	if err != nil {
		t.Fatalf("parseParties: %v", err)
	}
	byCode := map[string]ParsedParty{}
	for _, p := range parsed {
		byCode[p.TSECode] = p
	}

	tests := []struct {
		code        string
		wantAliases []string
	}{
		{code: "UNE", wantAliases: []string{"UNE"}},
		{code: "MPH", wantAliases: []string{"MPH", "Humanista"}},
		{code: "FCN-NACION", wantAliases: []string{"FCN-Nación", "FCN"}},
		{code: "CABAL", wantAliases: nil}, // empty alias cell
	}
	for _, tt := range tests {
		got, ok := byCode[tt.code]
		if !ok {
			t.Errorf("party %s missing from parsed set", tt.code)
			continue
		}
		if !stringSlicesEqual(got.Aliases, tt.wantAliases) {
			t.Errorf("party %s aliases: got %v want %v", tt.code, got.Aliases, tt.wantAliases)
		}
	}
}

func TestParseParties_UnknownStatusErrors(t *testing.T) {
	t.Parallel()
	bad := `<table>
        <tr class="party-row" data-tse-code="X" data-status="exploded">
            <td class="name">Bogus</td>
        </tr></table>`
	if _, err := parseParties(strings.NewReader(bad)); err == nil {
		t.Fatal("expected error for unknown status, got nil")
	}
}

func TestParseParties_EmptyDocErrors(t *testing.T) {
	t.Parallel()
	if _, err := parseParties(strings.NewReader("<html></html>")); err == nil {
		t.Fatal("expected error for empty doc, got nil")
	}
}

// fastClient returns a Client wired against srv with a 1ms backoff base so
// retry-path tests complete in well under a second.
func fastClient(srv *httptest.Server, ua string) *Client {
	return &Client{
		HTTPClient:  srv.Client(),
		UserAgent:   ua,
		URL:         srv.URL,
		MaxAttempts: 5,
		BackoffBase: 1 * time.Millisecond,
		MaxBackoff:  10 * time.Millisecond,
	}
}

func TestFetch_SendsRealChromeUA(t *testing.T) {
	t.Parallel()
	var gotUA atomic.Value
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotUA.Store(r.Header.Get("User-Agent"))
		_, _ = w.Write(readFixture(t))
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	if _, err := c.fetch(context.Background()); err != nil {
		t.Fatalf("fetch: %v", err)
	}
	ua, _ := gotUA.Load().(string)
	if ua == "" || strings.HasPrefix(ua, "Go-http-client") {
		t.Fatalf("UA was not the real-Chrome string: %q", ua)
	}
	if !strings.Contains(ua, "Chrome/") || !strings.Contains(ua, "Mozilla/5.0") {
		t.Fatalf("UA does not look like Chrome: %q", ua)
	}
}

func TestFetch_RetriesOn403(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := calls.Add(1)
		if n <= 2 {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	body, err := c.fetch(context.Background())
	if err != nil {
		t.Fatalf("fetch after retries: %v", err)
	}
	if string(body) != "ok" {
		t.Fatalf("body: got %q want %q", body, "ok")
	}
	if calls.Load() != 3 {
		t.Fatalf("expected 3 attempts (2 retries), got %d", calls.Load())
	}
}

func TestFetch_RetriesOn5xx(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := calls.Add(1)
		if n == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	if _, err := c.fetch(context.Background()); err != nil {
		t.Fatalf("fetch: %v", err)
	}
	if calls.Load() != 2 {
		t.Fatalf("expected 2 attempts (1 retry), got %d", calls.Load())
	}
}

func TestFetch_NonRetriable4xxFailsFast(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusNotFound)
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	_, err := c.fetch(context.Background())
	if err == nil {
		t.Fatal("expected error for 404, got nil")
	}
	if calls.Load() != 1 {
		t.Fatalf("expected exactly 1 attempt for non-retriable 404, got %d", calls.Load())
	}
}

func TestFetch_ExhaustsAttempts(t *testing.T) {
	t.Parallel()
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	_, err := c.fetch(context.Background())
	if err == nil {
		t.Fatal("expected error after exhausted attempts, got nil")
	}
	if calls.Load() != int32(c.MaxAttempts) {
		t.Fatalf("expected %d attempts, got %d", c.MaxAttempts, calls.Load())
	}
}

func TestBackoff_RespectsCap(t *testing.T) {
	t.Parallel()
	c := &Client{BackoffBase: 1 * time.Second, MaxBackoff: 10 * time.Second}
	for n := 0; n < 12; n++ {
		d := c.backoff(n)
		// ±20% jitter on the cap means worst-case is MaxBackoff * 1.2.
		if d > c.MaxBackoff*12/10 {
			t.Fatalf("backoff[%d] = %v exceeds cap+jitter %v", n, d, c.MaxBackoff*12/10)
		}
	}
}

// --- DB-gated integration tests below. Skip when POLITYK_TEST_DATABASE_URL
// is unset. The dsn must point at a database where migrations 0001-0003
// (or later) have been applied. ---

func openTestDB(t *testing.T) (*sql.DB, bool) {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set")
		return nil, false
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	if err := db.PingContext(context.Background()); err != nil {
		_ = db.Close()
		t.Skipf("DB not reachable: %v", err)
		return nil, false
	}
	return db, true
}

// truncateRelevantTables wipes the tables this scraper writes to. It runs
// before each integration test so the suite is independent of other rows
// that might be present from earlier work.
func truncateRelevantTables(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	for _, stmt := range []string{
		"TRUNCATE TABLE scrape_runs",
		"TRUNCATE TABLE party_aliases, parties RESTART IDENTITY CASCADE",
	} {
		if _, err := db.ExecContext(ctx, stmt); err != nil {
			t.Fatalf("truncate (%s): %v", stmt, err)
		}
	}
}

func newFixtureServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(readFixture(t))
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestRun_HappyPath_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateRelevantTables(t, db)
	srv := newFixtureServer(t)

	c := fastClient(srv, DefaultUserAgent)
	if err := c.Run(context.Background(), db); err != nil {
		t.Fatalf("Run: %v", err)
	}

	gotTotal, gotActive, gotCancelled, gotUnderAppeal := countPartiesByStatus(t, db)
	if gotTotal != 39 {
		t.Errorf("total parties: got %d want 39", gotTotal)
	}
	if gotActive != 28 {
		t.Errorf("active: got %d want 28", gotActive)
	}
	if gotCancelled != 10 {
		t.Errorf("cancelled: got %d want 10", gotCancelled)
	}
	if gotUnderAppeal != 1 {
		t.Errorf("cancelled_under_appeal: got %d want 1", gotUnderAppeal)
	}

	// Semilla flag survived the round-trip.
	var status string
	err := db.QueryRowContext(context.Background(),
		`SELECT status::text FROM parties WHERE tse_code = 'SEMILLA'`).Scan(&status)
	if err != nil {
		t.Fatalf("query Semilla: %v", err)
	}
	if status != string(StatusCancelledUnderAppeal) {
		t.Errorf("Semilla status: got %q want %q", status, StatusCancelledUnderAppeal)
	}

	// scrape_runs row was stamped with success=true.
	var success bool
	var lastRunAt time.Time
	err = db.QueryRowContext(context.Background(),
		`SELECT success, last_run_at FROM scrape_runs WHERE source = $1`, SourcePartyList).
		Scan(&success, &lastRunAt)
	if err != nil {
		t.Fatalf("query scrape_runs: %v", err)
	}
	if !success {
		t.Error("scrape_runs.success: got false want true")
	}
	if time.Since(lastRunAt) > 30*time.Second {
		t.Errorf("scrape_runs.last_run_at: %v looks stale", lastRunAt)
	}
}

func TestRun_Idempotent_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateRelevantTables(t, db)
	srv := newFixtureServer(t)

	c := fastClient(srv, DefaultUserAgent)
	if err := c.Run(context.Background(), db); err != nil {
		t.Fatalf("first Run: %v", err)
	}
	totalFirst, aliasesFirst := countPartiesAndAliases(t, db)

	if err := c.Run(context.Background(), db); err != nil {
		t.Fatalf("second Run: %v", err)
	}
	totalSecond, aliasesSecond := countPartiesAndAliases(t, db)

	if totalFirst != totalSecond {
		t.Errorf("parties count drifted: %d -> %d", totalFirst, totalSecond)
	}
	if aliasesFirst != aliasesSecond {
		t.Errorf("party_aliases count drifted: %d -> %d", aliasesFirst, aliasesSecond)
	}
}

func TestRun_StampsScrapeRunOnFailure_Integration(t *testing.T) {
	db, ok := openTestDB(t)
	if !ok {
		return
	}
	t.Cleanup(func() { _ = db.Close() })
	truncateRelevantTables(t, db)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(srv.Close)

	c := fastClient(srv, DefaultUserAgent)
	err := c.Run(context.Background(), db)
	if err == nil {
		t.Fatal("expected Run to fail after all retries, got nil")
	}

	var success bool
	var errMsg sql.NullString
	qerr := db.QueryRowContext(context.Background(),
		`SELECT success, error_message FROM scrape_runs WHERE source = $1`, SourcePartyList).
		Scan(&success, &errMsg)
	if errors.Is(qerr, sql.ErrNoRows) {
		t.Fatal("scrape_runs row not stamped on failure")
	}
	if qerr != nil {
		t.Fatalf("query scrape_runs: %v", qerr)
	}
	if success {
		t.Error("scrape_runs.success: got true want false")
	}
	if !errMsg.Valid || errMsg.String == "" {
		t.Error("scrape_runs.error_message: got empty want non-empty")
	}
}

func countPartiesByStatus(t *testing.T, db *sql.DB) (total, active, cancelled, underAppeal int) {
	t.Helper()
	ctx := context.Background()
	rows, err := db.QueryContext(ctx, `SELECT status::text, COUNT(*) FROM parties GROUP BY status`)
	if err != nil {
		t.Fatalf("count parties: %v", err)
	}
	defer func() { _ = rows.Close() }()
	for rows.Next() {
		var status string
		var n int
		if err := rows.Scan(&status, &n); err != nil {
			t.Fatalf("scan: %v", err)
		}
		total += n
		switch PartyStatus(status) {
		case StatusActive:
			active = n
		case StatusCancelled:
			cancelled = n
		case StatusCancelledUnderAppeal:
			underAppeal = n
		default:
			t.Fatalf("unexpected status in DB: %q", status)
		}
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows.Err: %v", err)
	}
	return total, active, cancelled, underAppeal
}

func countPartiesAndAliases(t *testing.T, db *sql.DB) (parties, aliases int) {
	t.Helper()
	ctx := context.Background()
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM parties`).Scan(&parties); err != nil {
		t.Fatalf("count parties: %v", err)
	}
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM party_aliases`).Scan(&aliases); err != nil {
		t.Fatalf("count party_aliases: %v", err)
	}
	return parties, aliases
}

func stringSlicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

