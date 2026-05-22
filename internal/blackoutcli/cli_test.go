package blackoutcli

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jlcp89/polityk/internal/middleware"
)

// fakeAudit captures InsertOverride calls and serves RecentOverrides from an
// in-memory slice so unit tests don't need a real Postgres.
type fakeAudit struct {
	inserted    []OverrideRow
	insertErr   error
	readErr     error
	recentLimit int
}

func (f *fakeAudit) InsertOverride(_ context.Context, action, reason, operator string) error {
	if f.insertErr != nil {
		return f.insertErr
	}
	f.inserted = append([]OverrideRow{{
		OverrideID: int64(len(f.inserted) + 1),
		Action:     action,
		Reason:     reason,
		Operator:   operator,
		CreatedAt:  time.Date(2026, 5, 22, 12, 0, 0, 0, time.UTC),
	}}, f.inserted...) // newest first to match SQL ORDER BY DESC
	return nil
}

func (f *fakeAudit) RecentOverrides(_ context.Context, limit int) ([]OverrideRow, error) {
	f.recentLimit = limit
	if f.readErr != nil {
		return nil, f.readErr
	}
	if limit > len(f.inserted) {
		limit = len(f.inserted)
	}
	return f.inserted[:limit], nil
}

func newOpts(t *testing.T, audit *fakeAudit, args ...string) (Options, *bytes.Buffer, *bytes.Buffer, string) {
	t.Helper()
	dir := t.TempDir()
	flagPath := filepath.Join(dir, "blackout.flag")
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	opts := Options{
		Args:     args,
		Stdout:   stdout,
		Stderr:   stderr,
		FlagFile: flagPath,
		UserEnv:  "test-operator",
		Now:      func() time.Time { return time.Date(2026, 5, 22, 12, 0, 0, 0, time.UTC) },
		Writer:   audit,
		Reader:   audit,
	}
	return opts, stdout, stderr, flagPath
}

func TestRun_Enable_WritesFlagAndAuditRow(t *testing.T) {
	audit := &fakeAudit{}
	opts, stdout, _, path := newOpts(t, audit, "enable", "--reason", "DST emergency")

	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read flag file: %v", err)
	}
	if string(got) != "true\n" {
		t.Errorf("flag file body: got %q want %q", got, "true\n")
	}
	if len(audit.inserted) != 1 {
		t.Fatalf("audit rows: got %d want 1", len(audit.inserted))
	}
	row := audit.inserted[0]
	if row.Action != "enabled" || row.Reason != "DST emergency" || row.Operator != "test-operator" {
		t.Errorf("audit row: got %+v", row)
	}
	if !strings.Contains(stdout.String(), "blackout enabled by test-operator") {
		t.Errorf("stdout: %q does not confirm flip", stdout.String())
	}
}

func TestRun_Disable_WritesFalseAndAuditRow(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, path := newOpts(t, audit, "disable", "--reason", "False alarm")

	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "false\n" {
		t.Errorf("flag file body: got %q want %q", got, "false\n")
	}
	if got := audit.inserted[0].Action; got != "disabled" {
		t.Errorf("action: got %q want disabled", got)
	}
}

func TestRun_EnableDisable_ProducesTwoAuditRows(t *testing.T) {
	audit := &fakeAudit{}
	opts1, _, _, _ := newOpts(t, audit, "enable", "--reason", "first")
	opts1.UserEnv = "alice"
	if err := Run(context.Background(), opts1); err != nil {
		t.Fatalf("enable: %v", err)
	}
	opts2 := opts1
	opts2.Args = []string{"disable", "--reason", "second"}
	opts2.UserEnv = "bob"
	if err := Run(context.Background(), opts2); err != nil {
		t.Fatalf("disable: %v", err)
	}
	if len(audit.inserted) != 2 {
		t.Fatalf("audit rows: got %d want 2", len(audit.inserted))
	}
	// newest-first ordering means inserted[0] is the disable
	if audit.inserted[0].Action != "disabled" || audit.inserted[1].Action != "enabled" {
		t.Errorf("ordering: got %q,%q", audit.inserted[0].Action, audit.inserted[1].Action)
	}
}

func TestRun_RejectsMissingReason(t *testing.T) {
	for _, action := range []string{"enable", "disable"} {
		t.Run(action, func(t *testing.T) {
			audit := &fakeAudit{}
			opts, _, stderr, _ := newOpts(t, audit, action)
			err := Run(context.Background(), opts)
			if err == nil {
				t.Fatalf("expected error for missing --reason")
			}
			if !errors.Is(err, ErrUsage) {
				t.Errorf("error is not ErrUsage: %v", err)
			}
			if !strings.Contains(stderr.String(), "--reason is required") {
				t.Errorf("stderr does not mention reason: %q", stderr.String())
			}
			if len(audit.inserted) != 0 {
				t.Errorf("audit row written despite usage error")
			}
		})
	}
}

func TestRun_RejectsEmptyReason(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, _ := newOpts(t, audit, "enable", "--reason", "   ")
	err := Run(context.Background(), opts)
	if !errors.Is(err, ErrUsage) {
		t.Fatalf("whitespace-only --reason: got %v want ErrUsage", err)
	}
	if len(audit.inserted) != 0 {
		t.Errorf("audit row written despite usage error")
	}
}

func TestRun_RejectsEmptyOperatorWhenUserUnset(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, _ := newOpts(t, audit, "enable", "--reason", "ok")
	opts.UserEnv = ""
	err := Run(context.Background(), opts)
	if !errors.Is(err, ErrUsage) {
		t.Fatalf("empty operator + $USER: got %v want ErrUsage", err)
	}
}

func TestRun_AcceptsExplicitOperator(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, _ := newOpts(t, audit, "enable", "--reason", "ok", "--operator", "oncall")
	opts.UserEnv = "" // $USER intentionally empty to prove --operator wins
	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if got := audit.inserted[0].Operator; got != "oncall" {
		t.Errorf("operator: got %q want oncall", got)
	}
}

func TestRun_Status_ReadsFlagFileAndLast5Rows(t *testing.T) {
	audit := &fakeAudit{}
	for i := 0; i < 7; i++ {
		_ = audit.InsertOverride(context.Background(), "enabled", "fill", "op")
	}
	opts, stdout, _, path := newOpts(t, audit, "status")
	if err := os.WriteFile(path, []byte("true\n"), 0o600); err != nil {
		t.Fatalf("seed flag file: %v", err)
	}

	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(stdout.String(), "blackout_enabled: true") {
		t.Errorf("status did not report flag=true: %q", stdout.String())
	}
	if !strings.Contains(stdout.String(), "last 5 audit rows") {
		t.Errorf("status did not report 5 rows: %q", stdout.String())
	}
	if audit.recentLimit != statusHistoryLimit {
		t.Errorf("limit: got %d want %d", audit.recentLimit, statusHistoryLimit)
	}
}

func TestRun_Status_NoFlagFileFallsBackToEnv(t *testing.T) {
	audit := &fakeAudit{}
	opts, stdout, _, path := newOpts(t, audit, "status")
	_ = os.Remove(path)
	opts.FlagFile = ""
	opts.EnvFlag = "true"

	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(stdout.String(), "blackout_enabled: true") {
		t.Errorf("env fallback missed: %q", stdout.String())
	}
	if !strings.Contains(stdout.String(), "env BLACKOUT_ENABLED") {
		t.Errorf("source label missing env mention: %q", stdout.String())
	}
}

func TestRun_Status_FlagFileMissingFallsBackToEnv(t *testing.T) {
	audit := &fakeAudit{}
	opts, stdout, _, path := newOpts(t, audit, "status")
	_ = os.Remove(path) // file is configured but absent
	opts.EnvFlag = "false"

	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(stdout.String(), "blackout_enabled: false") {
		t.Errorf("env fallback path: %q", stdout.String())
	}
}

func TestRun_Status_NoAuditWriter(t *testing.T) {
	opts, stdout, _, _ := newOpts(t, nil, "status")
	opts.Writer = nil
	opts.Reader = nil
	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if !strings.Contains(stdout.String(), "no DATABASE_URL") {
		t.Errorf("status should explain missing DB: %q", stdout.String())
	}
}

func TestRun_Status_RejectsExtraArgs(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, stderr, _ := newOpts(t, audit, "status", "extra")
	err := Run(context.Background(), opts)
	if !errors.Is(err, ErrUsage) {
		t.Fatalf("got %v want ErrUsage", err)
	}
	if !strings.Contains(stderr.String(), "unexpected argument") {
		t.Errorf("stderr: %q", stderr.String())
	}
}

func TestRun_RejectsUnknownSubcommand(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, stderr, _ := newOpts(t, audit, "panic")
	err := Run(context.Background(), opts)
	if !errors.Is(err, ErrUsage) {
		t.Fatalf("got %v want ErrUsage", err)
	}
	if !strings.Contains(stderr.String(), "unknown subcommand") {
		t.Errorf("stderr: %q", stderr.String())
	}
}

func TestRun_NoArgsPrintsUsage(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, stderr, _ := newOpts(t, audit)
	if err := Run(context.Background(), opts); !errors.Is(err, ErrUsage) {
		t.Fatalf("got %v want ErrUsage", err)
	}
	if !strings.Contains(stderr.String(), "usage:") {
		t.Errorf("stderr does not contain usage banner: %q", stderr.String())
	}
}

func TestRun_HelpPrintsUsageToStdout(t *testing.T) {
	audit := &fakeAudit{}
	opts, stdout, _, _ := newOpts(t, audit, "--help")
	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("--help: %v", err)
	}
	if !strings.Contains(stdout.String(), "usage:") {
		t.Errorf("stdout does not contain usage banner: %q", stdout.String())
	}
}

func TestRun_EnableRequiresFlagFile(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, _ := newOpts(t, audit, "enable", "--reason", "ok")
	opts.FlagFile = ""
	err := Run(context.Background(), opts)
	if err == nil || !strings.Contains(err.Error(), "BLACKOUT_FLAG_FILE") {
		t.Fatalf("expected BLACKOUT_FLAG_FILE error, got %v", err)
	}
}

func TestRun_EnableSurfacesAuditError(t *testing.T) {
	audit := &fakeAudit{insertErr: errors.New("db down")}
	opts, _, _, _ := newOpts(t, audit, "enable", "--reason", "ok")
	err := Run(context.Background(), opts)
	if err == nil || !strings.Contains(err.Error(), "db down") {
		t.Fatalf("expected db error to surface, got %v", err)
	}
}

// TestRun_FlagFlipVisibleToRunningAPI is the acceptance criterion's most
// load-bearing assertion: after `blackout enable` returns, the next request
// served by the same middleware instance sees the blackout state.
//
// This proves the "flip visible within 1 request" requirement without
// running a real HTTP server — the middleware's source of truth is the file
// at BLACKOUT_FLAG_FILE, which the CLI just wrote.
func TestRun_FlagFlipVisibleToRunningAPI(t *testing.T) {
	audit := &fakeAudit{}
	opts, _, _, path := newOpts(t, audit, "enable", "--reason", "DST emergency; resumed forecasts too early")

	t.Setenv("BLACKOUT_FLAG_FILE", path)
	t.Setenv("BLACKOUT_ENABLED", "")

	handler := middleware.Blackout(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Before any flip, the file is absent and the env is empty → 200.
	rec0 := httptest.NewRecorder()
	handler.ServeHTTP(rec0, httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil))
	if rec0.Code != http.StatusOK {
		t.Fatalf("pre-flip baseline: got %d want %d", rec0.Code, http.StatusOK)
	}

	// blackout enable → next request returns 503.
	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("enable: %v", err)
	}
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil))
	if rec1.Code != http.StatusServiceUnavailable {
		t.Fatalf("post-enable: got %d want %d", rec1.Code, http.StatusServiceUnavailable)
	}

	// blackout disable → next request returns 200 again.
	opts.Args = []string{"disable", "--reason", "All clear"}
	if err := Run(context.Background(), opts); err != nil {
		t.Fatalf("disable: %v", err)
	}
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil))
	if rec2.Code != http.StatusOK {
		t.Fatalf("post-disable: got %d want %d", rec2.Code, http.StatusOK)
	}

	if len(audit.inserted) != 2 {
		t.Errorf("audit rows: got %d want 2", len(audit.inserted))
	}
}

func TestWriteFlagFile_Atomicity(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "f")
	if err := writeFlagFile(path, "true"); err != nil {
		t.Fatalf("first write: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "true\n" {
		t.Errorf("first write contents: %q", got)
	}
	if err := writeFlagFile(path, "false"); err != nil {
		t.Fatalf("second write: %v", err)
	}
	got, _ = os.ReadFile(path)
	if string(got) != "false\n" {
		t.Errorf("second write contents: %q", got)
	}
	// No leftover *.tmp siblings — atomic rename cleaned up.
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".tmp") {
			t.Errorf("leftover temp file: %s", e.Name())
		}
	}
}
