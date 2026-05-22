package blackoutcli_test

import (
	"bytes"
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/jlcp89/polityk/internal/blackoutcli"
)

// blackoutTestDB mirrors the pattern in internal/store/*_integration_test.go:
// gated on POLITYK_TEST_DATABASE_URL so unit-only `go test ./...` keeps
// working without Postgres. Migrations 0001-0010 are expected to be applied.
func blackoutTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping blackout integration test")
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

// truncateOverrides clears the audit table at the start of each test so the
// tests are order-independent. We intentionally don't wrap in a transaction
// because the CLI opens its own connection in production usage; the cleanup
// approach matches the rest of the integration suite.
func truncateOverrides(t *testing.T, db *sql.DB) {
	t.Helper()
	if _, err := db.ExecContext(context.Background(), `TRUNCATE blackout_overrides RESTART IDENTITY`); err != nil {
		t.Fatalf("truncate: %v", err)
	}
}

func newIntegrationOpts(t *testing.T, db *sql.DB, args ...string) (blackoutcli.Options, *bytes.Buffer, string) {
	t.Helper()
	dir := t.TempDir()
	flagPath := filepath.Join(dir, "blackout.flag")
	stdout := &bytes.Buffer{}
	audit := &blackoutcli.SQLAudit{DB: db}
	return blackoutcli.Options{
		Args:     args,
		Stdout:   stdout,
		Stderr:   &bytes.Buffer{},
		FlagFile: flagPath,
		UserEnv:  "integration-test",
		Now:      time.Now,
		Writer:   audit,
		Reader:   audit,
	}, stdout, flagPath
}

// TestSchema_BlackoutOverridesCheckConstraints pins the contract migration
// 0010 commits to: action must be one of {'enabled','disabled'} and
// reason/operator must be non-empty.
func TestSchema_BlackoutOverridesCheckConstraints(t *testing.T) {
	db := blackoutTestDB(t)
	truncateOverrides(t, db)
	ctx := context.Background()

	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	t.Cleanup(func() { _ = tx.Rollback() })

	for _, bad := range []struct {
		name, action, reason, operator string
	}{
		{"unknown action", "paused", "ok", "op"},
		{"empty reason", "enabled", "", "op"},
		{"empty operator", "enabled", "ok", ""},
	} {
		t.Run(bad.name, func(t *testing.T) {
			if _, err := tx.ExecContext(ctx, `SAVEPOINT bad`); err != nil {
				t.Fatalf("savepoint: %v", err)
			}
			_, err := tx.ExecContext(ctx, `
				INSERT INTO blackout_overrides (action, reason, operator)
				VALUES ($1, $2, $3)
			`, bad.action, bad.reason, bad.operator)
			if err == nil {
				t.Errorf("expected CHECK violation for %s, got nil", bad.name)
			}
			if _, rbErr := tx.ExecContext(ctx, `ROLLBACK TO SAVEPOINT bad`); rbErr != nil {
				t.Fatalf("rollback: %v", rbErr)
			}
		})
	}
}

// TestEnableThenDisable_ProducesTwoAuditRows is the issue's headline
// integration check: end-to-end through the real CLI + real Postgres.
func TestEnableThenDisable_ProducesTwoAuditRows(t *testing.T) {
	db := blackoutTestDB(t)
	truncateOverrides(t, db)

	enableOpts, _, flagPath := newIntegrationOpts(t, db,
		"enable", "--reason", "DST emergency; resumed forecasts too early")
	if err := blackoutcli.Run(context.Background(), enableOpts); err != nil {
		t.Fatalf("enable: %v", err)
	}
	body, _ := os.ReadFile(flagPath)
	if string(body) != "true\n" {
		t.Errorf("flag file after enable: got %q want %q", body, "true\n")
	}

	disableOpts := enableOpts
	disableOpts.Args = []string{"disable", "--reason", "False alarm; flag was already set"}
	if err := blackoutcli.Run(context.Background(), disableOpts); err != nil {
		t.Fatalf("disable: %v", err)
	}
	body, _ = os.ReadFile(flagPath)
	if string(body) != "false\n" {
		t.Errorf("flag file after disable: got %q want %q", body, "false\n")
	}

	var count int
	if err := db.QueryRowContext(context.Background(),
		`SELECT COUNT(*) FROM blackout_overrides`).Scan(&count); err != nil {
		t.Fatalf("count: %v", err)
	}
	if count != 2 {
		t.Errorf("audit rows: got %d want 2", count)
	}

	rows, err := db.QueryContext(context.Background(), `
		SELECT action, reason, operator
		FROM blackout_overrides
		ORDER BY override_id ASC
	`)
	if err != nil {
		t.Fatalf("query: %v", err)
	}
	defer func() { _ = rows.Close() }()
	var got []struct{ action, reason, operator string }
	for rows.Next() {
		var r struct{ action, reason, operator string }
		if err := rows.Scan(&r.action, &r.reason, &r.operator); err != nil {
			t.Fatalf("scan: %v", err)
		}
		got = append(got, r)
	}
	if len(got) != 2 {
		t.Fatalf("scanned rows: got %d want 2", len(got))
	}
	if got[0].action != "enabled" || got[1].action != "disabled" {
		t.Errorf("action ordering: got %q,%q", got[0].action, got[1].action)
	}
	if got[0].operator != "integration-test" || got[1].operator != "integration-test" {
		t.Errorf("operator: got %q,%q", got[0].operator, got[1].operator)
	}
	if !strings.Contains(got[0].reason, "DST emergency") {
		t.Errorf("enable reason: %q", got[0].reason)
	}
	if !strings.Contains(got[1].reason, "False alarm") {
		t.Errorf("disable reason: %q", got[1].reason)
	}
}

// TestStatus_ReadsCurrentFlagAndAuditTail is the third acceptance check:
// `status` reports the effective flag + the last 5 rows from the real
// Postgres audit table.
func TestStatus_ReadsCurrentFlagAndAuditTail(t *testing.T) {
	db := blackoutTestDB(t)
	truncateOverrides(t, db)

	opts, _, flagPath := newIntegrationOpts(t, db, "enable", "--reason", "seed-1")
	// 7 inserts so `status` (which reads only the last 5) must drop the
	// first two. The reason length increases monotonically so we can
	// assert presence/absence of specific entries unambiguously.
	for i := 0; i < 7; i++ {
		opts.Args = []string{"enable", "--reason", "seed-" + strings.Repeat("x", i+1)}
		if err := blackoutcli.Run(context.Background(), opts); err != nil {
			t.Fatalf("seed enable %d: %v", i, err)
		}
	}

	statusStdout := &bytes.Buffer{}
	statusOpts := opts
	statusOpts.Args = []string{"status"}
	statusOpts.Stdout = statusStdout
	if err := blackoutcli.Run(context.Background(), statusOpts); err != nil {
		t.Fatalf("status: %v", err)
	}

	out := statusStdout.String()
	if !strings.Contains(out, "blackout_enabled: true") {
		t.Errorf("status output does not report flag=true: %q", out)
	}
	if !strings.Contains(out, "last 5 audit rows") {
		t.Errorf("status output does not show 5-row tail: %q", out)
	}
	// 7 inserts (1..7 x's). The most recent reason has 7 x's; the oldest
	// (1 x) should be dropped — only the last 5 are read.
	if !strings.Contains(out, "seed-xxxxxxx") {
		t.Errorf("status missing most-recent reason: %q", out)
	}
	if strings.Contains(out, "seed-x ") || strings.Contains(out, "seed-x\n") {
		t.Errorf("status leaked older reason 'seed-x' (1 x): %q", out)
	}
	// And the flag file still says true.
	body, _ := os.ReadFile(flagPath)
	if string(body) != "true\n" {
		t.Errorf("flag file: %q", body)
	}
}
