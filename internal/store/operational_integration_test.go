package store_test

import (
	"context"
	"database/sql"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	_ "github.com/jackc/pgx/v5/stdlib"
)

// operationalTestDB mirrors pollsTestDB / newsTestDB: gated on
// POLITYK_TEST_DATABASE_URL so unit-only `go test ./...` keeps working without
// Postgres. The DB is expected to have migrations 0001-0006 applied.
func operationalTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping operational integration test")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	t.Cleanup(func() {
		if cerr := db.Close(); cerr != nil {
			t.Logf("db close: %v", cerr)
		}
	})
	if err := db.PingContext(context.Background()); err != nil {
		t.Fatalf("ping: %v", err)
	}
	return db
}

// TestForecasts_PayloadIsJSONBAndRunKindCheck pins two structural guarantees
// the rest of the system relies on: the payload column type is JSONB (so the
// /v1/forecast/* handler in #9 can return it byte-for-byte) and the run_kind
// column rejects values outside {'scheduled','whatif'} (ADR-013/ADR-019).
func TestForecasts_PayloadIsJSONBAndRunKindCheck(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	var dataType string
	if err := db.QueryRowContext(ctx, `
		SELECT data_type FROM information_schema.columns
		WHERE table_name='forecasts' AND column_name='payload'
	`).Scan(&dataType); err != nil {
		t.Fatalf("information_schema query: %v", err)
	}
	if dataType != "jsonb" {
		t.Errorf("forecasts.payload data_type: got %q want \"jsonb\"", dataType)
	}

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	if _, err := tx.ExecContext(ctx, `SAVEPOINT bad_run_kind`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, run_kind, payload)
		VALUES ('0.1.0', 'presidential', 'bogus', '{}'::jsonb)
	`); err == nil {
		t.Fatalf("expected CHECK violation for run_kind='bogus', got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT bad_run_kind`); err != nil {
		t.Fatalf("rollback bad_run_kind: %v", err)
	}

	for _, kind := range []string{"scheduled", "whatif"} {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO forecasts (model_version, race_type, run_kind, payload)
			VALUES ('0.1.0', 'presidential', $1, '{"k":1}'::jsonb)
		`, kind); err != nil {
			t.Errorf("run_kind %q should be accepted: %v", kind, err)
		}
	}
}

// TestForecasts_DefaultsAndIsPublishedFalse pins the default values the
// publish gate (#36) and the methodology page (#13) rely on: run_kind defaults
// to 'scheduled', is_published to FALSE, and run_id to a fresh UUID.
func TestForecasts_DefaultsAndIsPublishedFalse(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var runID string
	var runKind string
	var isPublished bool
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload)
		VALUES ('0.1.0', 'presidential', '{}'::jsonb)
		RETURNING run_id::text, run_kind, is_published
	`).Scan(&runID, &runKind, &isPublished); err != nil {
		t.Fatalf("insert defaults: %v", err)
	}
	if runID == "" || len(runID) != 36 {
		t.Errorf("run_id default: got %q want a UUID", runID)
	}
	if runKind != "scheduled" {
		t.Errorf("run_kind default: got %q want \"scheduled\"", runKind)
	}
	if isPublished {
		t.Errorf("is_published default: got true want false")
	}
}

// TestPosteriorArchives_CascadeDeleteFollowsForecast walks the FK CASCADE
// invariant from ADR-006: deleting a forecast must take the matching posterior
// archive with it (the bytes are large and useless without a forecast row).
func TestPosteriorArchives_CascadeDeleteFollowsForecast(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var runID string
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload)
		VALUES ('0.1.0', 'presidential', '{}'::jsonb)
		RETURNING run_id::text
	`).Scan(&runID); err != nil {
		t.Fatalf("insert forecast: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO posterior_archives (run_id, race_type, sample_array)
		VALUES ($1::uuid, 'presidential', ARRAY[[0.4,0.3],[0.5,0.2]]::numeric[][])
	`, runID); err != nil {
		t.Fatalf("insert posterior: %v", err)
	}

	var before int
	if err := tx.QueryRowContext(ctx, `
		SELECT count(*) FROM posterior_archives WHERE run_id = $1::uuid
	`, runID).Scan(&before); err != nil {
		t.Fatalf("count before: %v", err)
	}
	if before != 1 {
		t.Fatalf("posterior_archives before delete: got %d want 1", before)
	}

	if _, err := tx.ExecContext(ctx, `DELETE FROM forecasts WHERE run_id = $1::uuid`, runID); err != nil {
		t.Fatalf("delete forecast: %v", err)
	}

	var after int
	if err := tx.QueryRowContext(ctx, `
		SELECT count(*) FROM posterior_archives WHERE run_id = $1::uuid
	`, runID).Scan(&after); err != nil {
		t.Fatalf("count after: %v", err)
	}
	if after != 0 {
		t.Errorf("posterior_archives after CASCADE delete: got %d want 0", after)
	}
}

// TestInterventions_OverrideProbabilityBoundsAndContract exercises the four
// rules baked into the interventions table:
//  1. override_probability ∈ [0, 1] when present
//  2. kind='manual_probability' ⇒ override_probability IS NOT NULL
//  3. kind ∈ other ⇒ override_probability IS NULL
//  4. reason and operator are non-empty.
func TestInterventions_OverrideProbabilityBoundsAndContract(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	type tc struct {
		name string
		exec string
		args []any
		ok   bool
	}
	const happyManual = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, override_probability, reason, operator)
		VALUES ('candidate', $1, 'manual_probability', now(), $2, 'TSE Acuerdo NNNN-2027', 'maintainer')`
	const noProbNonManual = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, reason, operator)
		VALUES ('candidate', $1, 'disqualified', now(), 'r', 'op')`
	const probOnNonManual = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, override_probability, reason, operator)
		VALUES ('candidate', $1, 'disqualified', now(), 0.5, 'r', 'op')`
	const manualNoProb = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, reason, operator)
		VALUES ('candidate', $1, 'manual_probability', now(), 'r', 'op')`
	const emptyReason = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, reason, operator)
		VALUES ('party', $1, 'party_cancelled', now(), '', 'op')`
	const emptyOperator = `
		INSERT INTO interventions
			(target_kind, target_id, kind, effective_at, reason, operator)
		VALUES ('party', $1, 'party_cancelled', now(), 'r', '')`

	cases := []tc{
		{"happy_lower_bound", happyManual, []any{int64(101), 0.0}, true},
		{"happy_upper_bound", happyManual, []any{int64(102), 1.0}, true},
		{"prob_above_one", happyManual, []any{int64(103), 1.5}, false},
		{"prob_below_zero", happyManual, []any{int64(104), -0.1}, false},
		{"happy_disqualified", noProbNonManual, []any{int64(105)}, true},
		{"non_manual_with_prob", probOnNonManual, []any{int64(106)}, false},
		{"manual_without_prob", manualNoProb, []any{int64(107)}, false},
		{"empty_reason", emptyReason, []any{int64(108)}, false},
		{"empty_operator", emptyOperator, []any{int64(109)}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if _, err := tx.ExecContext(ctx, `SAVEPOINT sp`); err != nil {
				t.Fatalf("savepoint: %v", err)
			}
			_, execErr := tx.ExecContext(ctx, c.exec, c.args...)
			if c.ok && execErr != nil {
				t.Errorf("expected success, got: %v", execErr)
			}
			if !c.ok && execErr == nil {
				t.Errorf("expected CHECK violation, got nil")
			}
			if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT sp`); err != nil {
				t.Fatalf("rollback to savepoint: %v", err)
			}
		})
	}
}

// TestCalibrationOverrides_RequireReasonAndOperator pins the #37
// force_publish.py audit-row contract: empty reason or operator must be
// rejected at the schema layer so the CLI can't silently bypass.
func TestCalibrationOverrides_RequireReasonAndOperator(t *testing.T) {
	db := operationalTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var runID string
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO forecasts (model_version, race_type, payload)
		VALUES ('0.1.0', 'presidential', '{}'::jsonb)
		RETURNING run_id::text
	`).Scan(&runID); err != nil {
		t.Fatalf("insert forecast: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `SAVEPOINT empty_reason`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO calibration_overrides (run_id, reason, operator)
		VALUES ($1::uuid, '', 'op')
	`, runID); err == nil {
		t.Errorf("expected CHECK violation for empty reason, got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT empty_reason`); err != nil {
		t.Fatalf("rollback empty_reason: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `SAVEPOINT empty_operator`); err != nil {
		t.Fatalf("savepoint: %v", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO calibration_overrides (run_id, reason, operator)
		VALUES ($1::uuid, 'r', '')
	`, runID); err == nil {
		t.Errorf("expected CHECK violation for empty operator, got nil")
	}
	if _, err := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT empty_operator`); err != nil {
		t.Fatalf("rollback empty_operator: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO calibration_overrides (run_id, reason, operator)
		VALUES ($1::uuid, 'DST emergency rollback', 'maintainer')
	`, runID); err != nil {
		t.Errorf("happy insert should succeed: %v", err)
	}
}

// TestForecastReady_ListenNotifyRoundTrip wires the ADR-006 LISTEN/NOTIFY
// contract: a separate pgx connection LISTENs on `forecast_ready`, and a
// NOTIFY fired from another connection arrives within a small timeout. The
// channel name is the operational contract between #33 (writer) and #10
// (Go cache invalidation goroutine).
func TestForecastReady_ListenNotifyRoundTrip(t *testing.T) {
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping LISTEN/NOTIFY test")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Listener connection: pgx.Conn is required (database/sql does not
	// expose LISTEN/NOTIFY; pgx's WaitForNotification needs a raw conn).
	listenConn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("listener pgx.Connect: %v", err)
	}
	defer func() { _ = listenConn.Close(context.Background()) }()
	if _, err := listenConn.Exec(ctx, `LISTEN forecast_ready`); err != nil {
		t.Fatalf("LISTEN: %v", err)
	}

	// Notifier connection: a separate conn so the LISTENer is genuinely
	// waiting on the wire when NOTIFY fires.
	notifyConn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("notifier pgx.Connect: %v", err)
	}
	defer func() { _ = notifyConn.Close(context.Background()) }()

	const payload = "test-run-id-issue-6"
	notifyDone := make(chan error, 1)
	go func() {
		// Give the listener a brief moment to be parked on
		// WaitForNotification before we fire. Without this, Postgres may
		// deliver the notify before the listener's read loop is ready,
		// which still works (notifications queue server-side) — but it
		// makes the test setup deterministic.
		time.Sleep(50 * time.Millisecond)
		_, err := notifyConn.Exec(ctx, `SELECT pg_notify('forecast_ready', $1)`, payload)
		notifyDone <- err
	}()

	waitCtx, waitCancel := context.WithTimeout(ctx, 5*time.Second)
	defer waitCancel()
	notif, err := listenConn.WaitForNotification(waitCtx)
	if err != nil {
		t.Fatalf("WaitForNotification: %v", err)
	}
	if notif.Channel != "forecast_ready" {
		t.Errorf("notification channel: got %q want \"forecast_ready\"", notif.Channel)
	}
	if notif.Payload != payload {
		t.Errorf("notification payload: got %q want %q", notif.Payload, payload)
	}

	if err := <-notifyDone; err != nil {
		t.Errorf("notifier Exec error: %v", err)
	}
}
