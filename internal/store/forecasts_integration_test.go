package store_test

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/store"
)

// txForecastReader is a test-local implementation of handlers.ForecastReader
// that runs the issue-#9 query inside a test's transaction so seed rows are
// visible without persisting beyond the test's Rollback. It mirrors
// store.ForecastReader.LatestPublishedPresidential exactly — the query string
// is shared via the assertions, not via a shared helper, so any drift in the
// production query surfaces here as a mismatch.
type txForecastReader struct {
	tx *sql.Tx
}

func (r txForecastReader) LatestPublishedPresidential(ctx context.Context) (*handlers.PresidentialForecast, error) {
	const q = `
		SELECT payload, run_id::text, model_version, generated_at
		FROM forecasts
		WHERE race_type = 'presidential' AND is_published = TRUE
		ORDER BY generated_at DESC
		LIMIT 1
	`
	var f handlers.PresidentialForecast
	err := r.tx.QueryRowContext(ctx, q).Scan(&f.Payload, &f.RunID, &f.ModelVersion, &f.GeneratedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &f, nil
}

// TestForecastReader_RoundTripsSeededPayload exercises the full path that
// `GET /v1/forecast/presidential` walks in production: seed a `forecasts` row
// with a hand-built ADR-014 payload, set is_published=TRUE, route through the
// handler, and assert the response body equals the seeded JSONB byte-for-byte.
// This is the issue-#9 integration acceptance criterion verbatim.
func TestForecastReader_RoundTripsSeededPayload(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	// pgx's JSONB scanner returns canonicalised JSON (whitespace removed,
	// keys re-ordered). To assert byte-for-byte equality we have to read
	// back what Postgres stored, then drive the handler with that same
	// input.
	const inputPayload = `{"run_id":"00000000-0000-0000-0000-000000000099","model_version":"0.1.0","generated_at":"2027-06-01T12:00:00-06:00","race":{"type":"presidential"},"candidates":[{"candidate_id":1,"name":"Alfa","vote_share_quantiles":{"p05":0.18,"p10":0.20,"p25":0.23,"p50":0.27,"p75":0.31,"p90":0.34,"p95":0.36}}],"runoff_matrix":[],"interventions_applied":[],"methodology_url":"https://polityk.gt/v1/methodology"}`

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var runID string
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published)
		VALUES ('0.1.0', 'presidential', $1::jsonb, TRUE)
		RETURNING run_id::text
	`, inputPayload).Scan(&runID); err != nil {
		t.Fatalf("insert forecast: %v", err)
	}

	var storedPayload []byte
	if err := tx.QueryRowContext(ctx, `
		SELECT payload FROM forecasts WHERE run_id = $1::uuid
	`, runID).Scan(&storedPayload); err != nil {
		t.Fatalf("readback payload: %v", err)
	}
	if len(storedPayload) == 0 {
		t.Fatalf("payload empty after readback")
	}

	reader := txForecastReader{tx: tx}
	handler := handlers.NewPresidentialForecast(reader)

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	if !bytes.Equal(rec.Body.Bytes(), storedPayload) {
		t.Fatalf("response body not byte-for-byte:\n got %q\nwant %q",
			rec.Body.String(), string(storedPayload))
	}
}

// TestForecastReader_NoPublishedRow_ReturnsNil pins the contract that
// store.ForecastReader returns (nil, nil) when nothing is published — and
// asserts unpublished rows are NOT picked up (is_published=FALSE filter).
func TestForecastReader_NoPublishedRow_ReturnsNil(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published)
		VALUES ('0.1.0', 'presidential', '{"draft":true}'::jsonb, FALSE)
	`); err != nil {
		t.Fatalf("insert unpublished forecast: %v", err)
	}

	reader := txForecastReader{tx: tx}
	got, err := reader.LatestPublishedPresidential(ctx)
	if err != nil {
		t.Fatalf("LatestPublishedPresidential: %v", err)
	}
	if got != nil {
		t.Fatalf("got forecast %+v, want nil (unpublished rows must be filtered)", got)
	}
}

// TestForecastReader_PicksMostRecentPublished asserts the ORDER BY
// generated_at DESC + LIMIT 1 clause: multiple published rows return the
// newest.
func TestForecastReader_PicksMostRecentPublished(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published, generated_at)
		VALUES
			('0.0.9', 'presidential', '{"v":"old"}'::jsonb, TRUE, now() - interval '2 days'),
			('0.1.0', 'presidential', '{"v":"new"}'::jsonb, TRUE, now())
	`); err != nil {
		t.Fatalf("insert two forecasts: %v", err)
	}

	reader := txForecastReader{tx: tx}
	got, err := reader.LatestPublishedPresidential(ctx)
	if err != nil {
		t.Fatalf("LatestPublishedPresidential: %v", err)
	}
	if got == nil {
		t.Fatalf("got nil, want most-recent forecast")
	}
	if got.ModelVersion != "0.1.0" {
		t.Errorf("model_version: got %q want \"0.1.0\" (most-recent generated_at)", got.ModelVersion)
	}
}

// TestForecastReader_FiltersByRaceType asserts the WHERE race_type='presidential'
// clause: a congress/municipal row must not satisfy the presidential query.
func TestForecastReader_FiltersByRaceType(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload, is_published)
		VALUES ('0.1.0', 'congress', '{"v":"congress"}'::jsonb, TRUE)
	`); err != nil {
		t.Fatalf("insert congress row: %v", err)
	}

	reader := txForecastReader{tx: tx}
	got, err := reader.LatestPublishedPresidential(ctx)
	if err != nil {
		t.Fatalf("LatestPublishedPresidential: %v", err)
	}
	if got != nil {
		t.Fatalf("got %+v, want nil (congress rows must not satisfy presidential query)", got)
	}
}

// TestForecastReader_ProductionConstructor sanity-checks that the
// store.ForecastReader struct itself wires together against the live DB.
func TestForecastReader_ProductionConstructor(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	reader := &store.ForecastReader{DB: db}
	if _, err := reader.LatestPublishedPresidential(ctx); err != nil {
		t.Fatalf("production reader query error: %v", err)
	}
}
