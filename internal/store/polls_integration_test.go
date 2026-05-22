package store_test

import (
	"context"
	"database/sql"
	"os"
	"testing"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// pollsTestDB connects to the polityk test database identified by
// POLITYK_TEST_DATABASE_URL. The test is skipped when the env var is empty
// so the unit-only `go test ./...` workflow keeps working without Postgres.
// The DB is expected to have all migrations applied; the test runs inside a
// transaction that is always rolled back so it never pollutes shared state.
func pollsTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping polls integration test")
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

func TestPolls_SeededPollstersHaveDefaultBiasPrior(t *testing.T) {
	db := pollsTestDB(t)
	ctx := context.Background()

	rows, err := db.QueryContext(ctx, `
		SELECT name, historical_bias_mean, historical_bias_sd, sample_count_used
		FROM pollsters
		WHERE name IN ('CID Gallup','ProDatos','Borge y Asociados','Fundación Libertad y Desarrollo')
		ORDER BY name
	`)
	if err != nil {
		t.Fatalf("query pollsters: %v", err)
	}
	defer rows.Close()

	type pollsterRow struct {
		name             string
		biasMean, biasSD float64
		sampleCount      int
	}
	var got []pollsterRow
	for rows.Next() {
		var p pollsterRow
		if err := rows.Scan(&p.name, &p.biasMean, &p.biasSD, &p.sampleCount); err != nil {
			t.Fatalf("scan: %v", err)
		}
		got = append(got, p)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows.Err: %v", err)
	}
	if len(got) != 4 {
		t.Fatalf("seeded pollster count: got %d want 4", len(got))
	}
	for _, p := range got {
		if p.biasMean != 0.0 {
			t.Errorf("%s historical_bias_mean: got %v want 0", p.name, p.biasMean)
		}
		if p.biasSD != 0.05 {
			t.Errorf("%s historical_bias_sd: got %v want 0.05", p.name, p.biasSD)
		}
		if p.sampleCount != 0 {
			t.Errorf("%s sample_count_used: got %d want 0", p.name, p.sampleCount)
		}
	}
}

func TestPolls_InsertAndJoin(t *testing.T) {
	db := pollsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var pollsterID int64
	if err := tx.QueryRowContext(ctx,
		`SELECT pollster_id FROM pollsters WHERE name = 'CID Gallup'`,
	).Scan(&pollsterID); err != nil {
		t.Fatalf("lookup CID Gallup: %v", err)
	}

	var candidateID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ($1) RETURNING candidate_id
	`, "Integration Test Candidate").Scan(&candidateID); err != nil {
		t.Fatalf("insert candidate: %v", err)
	}

	var pollID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO polls (pollster_id, field_start, field_end, sample_size, methodology, source_url)
		VALUES ($1, '2027-04-01', '2027-04-10', 1200, 'National face-to-face', 'https://example.com/itest-1')
		RETURNING poll_id
	`, pollsterID).Scan(&pollID); err != nil {
		t.Fatalf("insert poll: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO poll_responses (poll_id, candidate_id, share, margin_of_error)
		VALUES ($1, $2, 0.42, 0.025)
	`, pollID, candidateID); err != nil {
		t.Fatalf("insert poll_response: %v", err)
	}

	var (
		gotPollster string
		gotName     string
		gotShare    float64
		gotMOE      float64
	)
	if err := tx.QueryRowContext(ctx, `
		SELECT p.name, c.full_name, pr.share, pr.margin_of_error
		FROM polls pls
		JOIN pollsters p     ON p.pollster_id  = pls.pollster_id
		JOIN poll_responses pr ON pr.poll_id   = pls.poll_id
		JOIN candidates c    ON c.candidate_id = pr.candidate_id
		WHERE pls.poll_id = $1
	`, pollID).Scan(&gotPollster, &gotName, &gotShare, &gotMOE); err != nil {
		t.Fatalf("join select: %v", err)
	}
	if gotPollster != "CID Gallup" {
		t.Errorf("pollster: got %q want %q", gotPollster, "CID Gallup")
	}
	if gotName != "Integration Test Candidate" {
		t.Errorf("candidate: got %q want %q", gotName, "Integration Test Candidate")
	}
	if gotShare != 0.42 {
		t.Errorf("share: got %v want 0.42", gotShare)
	}
	if gotMOE != 0.025 {
		t.Errorf("margin_of_error: got %v want 0.025", gotMOE)
	}
}

func TestPolls_ErrorGeneratedColumnUpdatesAutomatically(t *testing.T) {
	db := pollsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var pollsterID int64
	if err := tx.QueryRowContext(ctx,
		`SELECT pollster_id FROM pollsters WHERE name = 'ProDatos'`,
	).Scan(&pollsterID); err != nil {
		t.Fatalf("lookup ProDatos: %v", err)
	}
	var candidateID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ($1) RETURNING candidate_id
	`, "Error Generated Column Candidate").Scan(&candidateID); err != nil {
		t.Fatalf("insert candidate: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO poll_errors (pollster_id, cycle, candidate_id, poll_prediction, actual_result)
		VALUES ($1, 2023, $2, 0.42, 0.38)
	`, pollsterID, candidateID); err != nil {
		t.Fatalf("insert poll_error: %v", err)
	}

	var gotErr float64
	if err := tx.QueryRowContext(ctx, `
		SELECT error FROM poll_errors WHERE pollster_id=$1 AND cycle=2023 AND candidate_id=$2
	`, pollsterID, candidateID).Scan(&gotErr); err != nil {
		t.Fatalf("select error col: %v", err)
	}
	if got, want := round4(gotErr), 0.04; got != want {
		t.Fatalf("generated error after insert: got %v want %v", got, want)
	}

	if _, err := tx.ExecContext(ctx, `
		UPDATE poll_errors SET poll_prediction = 0.50
		WHERE pollster_id=$1 AND cycle=2023 AND candidate_id=$2
	`, pollsterID, candidateID); err != nil {
		t.Fatalf("update poll_prediction: %v", err)
	}

	if err := tx.QueryRowContext(ctx, `
		SELECT error FROM poll_errors WHERE pollster_id=$1 AND cycle=2023 AND candidate_id=$2
	`, pollsterID, candidateID).Scan(&gotErr); err != nil {
		t.Fatalf("select error col after update: %v", err)
	}
	if got, want := round4(gotErr), 0.12; got != want {
		t.Fatalf("generated error after update: got %v want %v", got, want)
	}
}

func TestPolls_ShareCheckConstraint(t *testing.T) {
	db := pollsTestDB(t)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin tx: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	var pollsterID int64
	if err := tx.QueryRowContext(ctx,
		`SELECT pollster_id FROM pollsters WHERE name = 'Borge y Asociados'`,
	).Scan(&pollsterID); err != nil {
		t.Fatalf("lookup Borge: %v", err)
	}
	var candidateID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO candidates (full_name) VALUES ($1) RETURNING candidate_id
	`, "Share Check Candidate").Scan(&candidateID); err != nil {
		t.Fatalf("insert candidate: %v", err)
	}
	var pollID int64
	if err := tx.QueryRowContext(ctx, `
		INSERT INTO polls (pollster_id, field_start, field_end, source_url)
		VALUES ($1, '2027-04-01', '2027-04-10', 'https://example.com/itest-share')
		RETURNING poll_id
	`, pollsterID).Scan(&pollID); err != nil {
		t.Fatalf("insert poll: %v", err)
	}

	if _, err := tx.ExecContext(ctx, `
		INSERT INTO poll_responses (poll_id, candidate_id, share) VALUES ($1, $2, 1.5)
	`, pollID, candidateID); err == nil {
		t.Fatalf("expected CHECK violation for share>1, got nil")
	}
}

// round4 trims floating-point noise from NUMERIC -> float64 conversions so
// equality assertions on simple subtractions are stable.
func round4(x float64) float64 {
	const k = 10000.0
	if x >= 0 {
		return float64(int64(x*k+0.5)) / k
	}
	return float64(int64(x*k-0.5)) / k
}
