package listener_test

import (
	"context"
	"log/slog"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/jlcp89/polityk/internal/listener"
)

// integrationDSN gates the integration tests on POLITYK_TEST_DATABASE_URL
// (same env var as the rest of the suite). When unset, the chaos test
// skips so unit-only `go test ./...` keeps working.
func integrationDSN(t *testing.T) string {
	t.Helper()
	dsn := os.Getenv("POLITYK_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("POLITYK_TEST_DATABASE_URL not set; skipping listener integration test")
	}
	return dsn
}

type countingInvalidator struct {
	clears atomic.Int64
}

func (c *countingInvalidator) Clear() { c.clears.Add(1) }

// TestListener_LiveNotifyClearsCache_Integration is the happy-path
// acceptance criterion: a real Postgres `NOTIFY forecast_ready` reaches
// the listener and triggers Clear() within a second.
func TestListener_LiveNotifyClearsCache_Integration(t *testing.T) {
	dsn := integrationDSN(t)

	cache := &countingInvalidator{}
	l := &listener.Listener{
		DSN:            dsn,
		Cache:          cache,
		InitialBackoff: 50 * time.Millisecond,
		MaxBackoff:     200 * time.Millisecond,
		Logger:         slog.Default(),
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	// Give the listener a brief moment to LISTEN before firing NOTIFY.
	time.Sleep(200 * time.Millisecond)

	notifier, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("notifier connect: %v", err)
	}
	defer func() { _ = notifier.Close(context.Background()) }()
	if _, err := notifier.Exec(ctx, `SELECT pg_notify($1, $2)`, listener.Channel, "live-test"); err != nil {
		t.Fatalf("pg_notify: %v", err)
	}

	deadline := time.Now().Add(3 * time.Second)
	for cache.clears.Load() < 1 {
		if time.Now().After(deadline) {
			t.Fatalf("clears within 3s: got %d want >=1", cache.clears.Load())
		}
		time.Sleep(5 * time.Millisecond)
	}
	cancel()
	<-done
}

// TestListener_ReconnectsAfterBackendTerminated_Integration is the chaos
// acceptance criterion. Instead of `pkill -9 postgres` (which would tear
// down the test DB the rest of the suite relies on), we issue
// `pg_terminate_backend(pid)` against the listener's own session — pgx
// surfaces this as a connection error, the loop reconnects, and a
// follow-up NOTIFY then exercises the recovered path.
//
// The 30-second budget in the issue body covers postgres restart latency
// in production; here the recovery is sub-second (just a TCP reconnect).
func TestListener_ReconnectsAfterBackendTerminated_Integration(t *testing.T) {
	dsn := integrationDSN(t)

	cache := &countingInvalidator{}
	l := &listener.Listener{
		DSN:            dsn,
		Cache:          cache,
		InitialBackoff: 50 * time.Millisecond,
		MaxBackoff:     500 * time.Millisecond,
		Logger:         slog.Default(),
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	// First, prove the listener is healthy: fire NOTIFY, see one Clear().
	time.Sleep(200 * time.Millisecond)
	notifier, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("notifier connect: %v", err)
	}
	defer func() { _ = notifier.Close(context.Background()) }()
	if _, err := notifier.Exec(ctx, `SELECT pg_notify($1, 'pre-chaos')`, listener.Channel); err != nil {
		t.Fatalf("pre-chaos notify: %v", err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for cache.clears.Load() < 1 {
		if time.Now().After(deadline) {
			t.Fatalf("pre-chaos clears: got %d want 1", cache.clears.Load())
		}
		time.Sleep(5 * time.Millisecond)
	}

	// Chaos: kill every other backend that is on `forecast_ready`. The
	// listener's session is the one with state='idle' running
	// `LISTEN forecast_ready`. pg_terminate_backend signals the backend,
	// pgx's WaitForNotification returns an error, the loop reconnects.
	preChaosClears := cache.clears.Load()
	if _, err := notifier.Exec(ctx, `
		SELECT pg_terminate_backend(pid)
		FROM pg_stat_activity
		WHERE pid <> pg_backend_pid()
		  AND query ILIKE 'LISTEN%forecast_ready%'
	`); err != nil {
		t.Fatalf("pg_terminate_backend: %v", err)
	}

	// Drive reconnect with retried NOTIFY: the listener may take a
	// backoff cycle to come back online; keep firing pings until the
	// counter advances.
	deadline = time.Now().Add(10 * time.Second)
	for cache.clears.Load() <= preChaosClears {
		if time.Now().After(deadline) {
			t.Fatalf("post-chaos clears: got %d want > %d (listener did not reconnect within 10s)",
				cache.clears.Load(), preChaosClears)
		}
		_, _ = notifier.Exec(ctx, `SELECT pg_notify($1, 'post-chaos')`, listener.Channel)
		time.Sleep(50 * time.Millisecond)
	}

	cancel()
	<-done
}
