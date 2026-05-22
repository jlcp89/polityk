// Package blackoutcli implements the manual blackout override CLI (#46) per
// ADR-003. It is invoked by `cmd/blackout` and tested as a library so the
// integration tests can drive it without exec'ing a subprocess.
//
// The CLI lives at the legal-control boundary. Its responsibilities:
//
//  1. Persist the operator's intent to flip the blackout flag by writing
//     "true\n" or "false\n" to the path in BLACKOUT_FLAG_FILE. The Go API
//     middleware (internal/middleware/blackout.go) reads this file fresh on
//     every request, so the next request to /v1/forecast/* picks up the
//     flip without a process restart.
//  2. Write an audit row to blackout_overrides (action, reason, operator,
//     created_at) for every flip — never silent.
//  3. Reject empty --reason at the CLI boundary; the table-level CHECK is
//     the last line of defence (length(reason) > 0).
//
// `status` reads the current effective flag (file → env fallback) and the
// last 5 audit rows. It performs NO writes — safe to run on any host.
package blackoutcli

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// EnvFlagFile names the file the middleware reads on each request to decide
// whether the blackout is active. The CLI writes "true\n" / "false\n" here.
// Mirrors middleware.blackoutFlagFileEnv but kept as its own constant so the
// CLI is decoupled from middleware import side-effects.
const EnvFlagFile = "BLACKOUT_FLAG_FILE"

// EnvBlackoutEnabled is the env-var fallback path. Read only by `status` to
// echo back the effective flag state when no flag file is configured.
const EnvBlackoutEnabled = "BLACKOUT_ENABLED"

// statusHistoryLimit is the number of recent audit rows `status` reports.
// Fixed at 5 per the issue's acceptance criterion.
const statusHistoryLimit = 5

// ErrUsage is returned for argument-shape problems (unknown subcommand,
// missing required flag). Main.go converts this into a usage banner +
// exit 2. Other errors map to exit 1.
var ErrUsage = errors.New("usage")

// AuditInserter is the narrow DB seam the CLI uses for writes. The
// integration test substitutes a real *sql.DB; unit tests can supply a fake.
type AuditInserter interface {
	InsertOverride(ctx context.Context, action, reason, operator string) error
}

// AuditReader reads the last N audit rows in descending order. Used only by
// `status`. Separated from AuditInserter so a read-only smoke test of
// `status` doesn't need to satisfy the writer.
type AuditReader interface {
	RecentOverrides(ctx context.Context, limit int) ([]OverrideRow, error)
}

// OverrideRow is the in-memory shape of a blackout_overrides row, used by
// `status` to render the recent-history table.
type OverrideRow struct {
	OverrideID int64
	Action     string
	Reason     string
	Operator   string
	CreatedAt  time.Time
}

// Options bundles the inputs the CLI needs from its environment. Carved out
// from os.* so tests can drive the CLI without monkey-patching globals.
type Options struct {
	Args     []string  // argv[1:]
	Stdout   io.Writer // for command output (status table, success line)
	Stderr   io.Writer // for usage banners + error lines
	Stdin    io.Reader // unused today; reserved for an interactive confirm if ever needed
	FlagFile string    // BLACKOUT_FLAG_FILE — required for enable/disable
	EnvFlag  string    // BLACKOUT_ENABLED — read by `status` when FlagFile absent
	UserEnv  string    // value of $USER (default operator)
	Now      func() time.Time
	Writer   AuditInserter
	Reader   AuditReader
}

// Run dispatches a single CLI invocation. Returns:
//   - nil on success
//   - ErrUsage (wrapped) for argument-shape problems → exit 2
//   - any other error for runtime failures → exit 1
func Run(ctx context.Context, opts Options) error {
	if len(opts.Args) == 0 {
		printUsage(opts.Stderr)
		return ErrUsage
	}
	sub := opts.Args[0]
	rest := opts.Args[1:]
	switch sub {
	case "enable":
		return runFlip(ctx, opts, rest, "enabled", "true")
	case "disable":
		return runFlip(ctx, opts, rest, "disabled", "false")
	case "status":
		return runStatus(ctx, opts, rest)
	case "-h", "--help", "help":
		printUsage(opts.Stdout)
		return nil
	default:
		fmt.Fprintf(opts.Stderr, "blackout: unknown subcommand %q\n", sub)
		printUsage(opts.Stderr)
		return fmt.Errorf("%w: unknown subcommand %q", ErrUsage, sub)
	}
}

func runFlip(ctx context.Context, opts Options, rest []string, action, flagValue string) error {
	reason, operator, err := parseFlipFlags(opts, rest, action)
	if err != nil {
		return err
	}
	if opts.FlagFile == "" {
		return fmt.Errorf("BLACKOUT_FLAG_FILE env var must be set (path the API reads per ADR-003)")
	}
	if opts.Writer == nil {
		return fmt.Errorf("audit writer not configured (no DATABASE_URL?)")
	}

	if err := writeFlagFile(opts.FlagFile, flagValue); err != nil {
		return fmt.Errorf("write flag file %q: %w", opts.FlagFile, err)
	}
	if err := opts.Writer.InsertOverride(ctx, action, reason, operator); err != nil {
		return fmt.Errorf("insert blackout_overrides row: %w", err)
	}

	fmt.Fprintf(opts.Stdout, "blackout %s by %s — flag file %s set to %s\n",
		action, operator, opts.FlagFile, flagValue)
	fmt.Fprintf(opts.Stdout, "reason: %s\n", reason)
	return nil
}

func parseFlipFlags(opts Options, rest []string, action string) (reason, operator string, err error) {
	fs := flag.NewFlagSet("blackout "+action, flag.ContinueOnError)
	fs.SetOutput(opts.Stderr)
	fs.StringVar(&reason, "reason", "", "non-empty justification recorded in blackout_overrides.reason")
	fs.StringVar(&operator, "operator", "", "operator id recorded in blackout_overrides.operator (default $USER)")
	if perr := fs.Parse(rest); perr != nil {
		return "", "", fmt.Errorf("%w: %v", ErrUsage, perr)
	}
	if strings.TrimSpace(reason) == "" {
		fmt.Fprintln(opts.Stderr, "blackout: --reason is required and must be non-empty")
		return "", "", fmt.Errorf("%w: --reason required", ErrUsage)
	}
	if strings.TrimSpace(operator) == "" {
		operator = strings.TrimSpace(opts.UserEnv)
	}
	if strings.TrimSpace(operator) == "" {
		fmt.Fprintln(opts.Stderr, "blackout: --operator is required (or set $USER)")
		return "", "", fmt.Errorf("%w: --operator required when $USER is empty", ErrUsage)
	}
	return reason, operator, nil
}

func runStatus(ctx context.Context, opts Options, rest []string) error {
	if len(rest) > 0 {
		fmt.Fprintf(opts.Stderr, "blackout status: unexpected argument %q\n", rest[0])
		return fmt.Errorf("%w: status takes no arguments", ErrUsage)
	}
	state, source := currentFlag(opts)
	fmt.Fprintf(opts.Stdout, "blackout_enabled: %t (source: %s)\n", state, source)
	if opts.Reader == nil {
		fmt.Fprintln(opts.Stdout, "audit log: (skipped — no DATABASE_URL configured)")
		return nil
	}
	rows, err := opts.Reader.RecentOverrides(ctx, statusHistoryLimit)
	if err != nil {
		return fmt.Errorf("read blackout_overrides: %w", err)
	}
	if len(rows) == 0 {
		fmt.Fprintln(opts.Stdout, "audit log: (no rows yet)")
		return nil
	}
	fmt.Fprintf(opts.Stdout, "last %d audit rows (most recent first):\n", len(rows))
	for _, r := range rows {
		fmt.Fprintf(opts.Stdout, "  #%d  %s  %-8s by %s — %s\n",
			r.OverrideID,
			r.CreatedAt.UTC().Format(time.RFC3339),
			r.Action,
			r.Operator,
			r.Reason)
	}
	return nil
}

// currentFlag returns (active, source). Source describes which input was
// consulted so `status` is honest about *why* the flag reads the way it
// does — operators debug flag mismatches by reading this line first.
func currentFlag(opts Options) (bool, string) {
	if opts.FlagFile != "" {
		raw, err := os.ReadFile(opts.FlagFile)
		switch {
		case err == nil:
			trimmed := strings.TrimSpace(string(raw))
			if trimmed == "" {
				return false, fmt.Sprintf("file %s (empty → off)", opts.FlagFile)
			}
			v, perr := strconv.ParseBool(trimmed)
			if perr != nil {
				return false, fmt.Sprintf("file %s (unparseable %q → off)", opts.FlagFile, trimmed)
			}
			return v, fmt.Sprintf("file %s", opts.FlagFile)
		case os.IsNotExist(err):
			// fall through to env
		default:
			return false, fmt.Sprintf("file %s (read error: %v → off)", opts.FlagFile, err)
		}
	}
	v, err := strconv.ParseBool(opts.EnvFlag)
	if err != nil {
		return false, "env BLACKOUT_ENABLED (unset or unparseable → off)"
	}
	return v, "env BLACKOUT_ENABLED"
}

// writeFlagFile writes value+"\n" to path atomically: write to a temp file
// in the same directory, fsync, rename. Atomicity matters because the
// middleware reads the file on every request and we'd rather have a brief
// "old true" window than a half-written "tru" that ParseBool rejects.
func writeFlagFile(path, value string) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".blackout-flag-*.tmp")
	if err != nil {
		return fmt.Errorf("create temp: %w", err)
	}
	tmpName := tmp.Name()
	cleanup := func() { _ = os.Remove(tmpName) }
	if _, err := io.WriteString(tmp, value+"\n"); err != nil {
		_ = tmp.Close()
		cleanup()
		return fmt.Errorf("write temp: %w", err)
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		cleanup()
		return fmt.Errorf("sync temp: %w", err)
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return fmt.Errorf("close temp: %w", err)
	}
	if err := os.Rename(tmpName, path); err != nil {
		cleanup()
		return fmt.Errorf("rename temp into place: %w", err)
	}
	return nil
}

func printUsage(w io.Writer) {
	fmt.Fprintln(w, "usage: blackout <enable|disable|status> [flags]")
	fmt.Fprintln(w, "")
	fmt.Fprintln(w, "  enable  --reason <text> [--operator <name>]")
	fmt.Fprintln(w, "          flip BLACKOUT to ON, record audit row")
	fmt.Fprintln(w, "  disable --reason <text> [--operator <name>]")
	fmt.Fprintln(w, "          flip BLACKOUT to OFF, record audit row")
	fmt.Fprintln(w, "  status")
	fmt.Fprintln(w, "          print effective flag + last 5 audit rows")
	fmt.Fprintln(w, "")
	fmt.Fprintln(w, "env:")
	fmt.Fprintln(w, "  BLACKOUT_FLAG_FILE  path the Go API reads each request (required for enable/disable)")
	fmt.Fprintln(w, "  DATABASE_URL        Postgres DSN for the audit log")
	fmt.Fprintln(w, "  BLACKOUT_ENABLED    fallback when no flag file is set (read by status)")
}

// SQLAudit is the production AuditInserter + AuditReader backed by a real
// *sql.DB. Kept in this package so cmd/blackout doesn't need its own
// store package.
type SQLAudit struct {
	DB *sql.DB
}

func (s *SQLAudit) InsertOverride(ctx context.Context, action, reason, operator string) error {
	if s == nil || s.DB == nil {
		return errors.New("nil DB")
	}
	_, err := s.DB.ExecContext(ctx, `
		INSERT INTO blackout_overrides (action, reason, operator)
		VALUES ($1, $2, $3)
	`, action, reason, operator)
	return err
}

func (s *SQLAudit) RecentOverrides(ctx context.Context, limit int) ([]OverrideRow, error) {
	if s == nil || s.DB == nil {
		return nil, errors.New("nil DB")
	}
	rows, err := s.DB.QueryContext(ctx, `
		SELECT override_id, action, reason, operator, created_at
		FROM blackout_overrides
		ORDER BY override_id DESC
		LIMIT $1
	`, limit)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var out []OverrideRow
	for rows.Next() {
		var r OverrideRow
		if scanErr := rows.Scan(&r.OverrideID, &r.Action, &r.Reason, &r.Operator, &r.CreatedAt); scanErr != nil {
			return nil, scanErr
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
