package listener_test

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgconn"

	"github.com/jlcp89/polityk/internal/listener"
)

func runtimeNumGoroutines(t *testing.T) int {
	t.Helper()
	return runtime.NumGoroutine()
}

// fakeInvalidator counts Clear() calls so a test can assert the cache was
// hit exactly N times after a known number of notifications.
type fakeInvalidator struct {
	clears atomic.Int64
}

func (f *fakeInvalidator) Clear() { f.clears.Add(1) }

// fakeConn is a programmable listener.Conn: each call to WaitForNotification
// pulls the next event from a channel. EOF returns an error to trigger the
// reconnect path; a sentinel string in the value's Payload field marks a
// notification.
type fakeConn struct {
	notify   chan *pgconn.Notification
	dropErr  error
	closed   atomic.Bool
	execErr  error
	execCall atomic.Int64
}

func (c *fakeConn) Exec(_ context.Context, _ string, _ ...any) (pgconn.CommandTag, error) {
	c.execCall.Add(1)
	if c.execErr != nil {
		return pgconn.CommandTag{}, c.execErr
	}
	return pgconn.CommandTag{}, nil
}

func (c *fakeConn) WaitForNotification(ctx context.Context) (*pgconn.Notification, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case n, ok := <-c.notify:
		if !ok {
			return nil, c.dropErr
		}
		return n, nil
	}
}

func (c *fakeConn) Close(_ context.Context) error {
	c.closed.Store(true)
	return nil
}

// captureLogger returns a slog.Logger that writes JSON lines to buf so
// tests can assert the four mandatory structured event names appear.
func captureLogger(buf *bytes.Buffer) *slog.Logger {
	return slog.New(slog.NewJSONHandler(buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

func TestListener_ClearsCacheOnEachNotification(t *testing.T) {
	t.Parallel()

	cache := &fakeInvalidator{}
	conn := &fakeConn{notify: make(chan *pgconn.Notification, 3)}
	var buf bytes.Buffer

	l := &listener.Listener{
		DSN:            "ignored",
		Cache:          cache,
		InitialBackoff: 10 * time.Millisecond,
		MaxBackoff:     20 * time.Millisecond,
		Logger:         captureLogger(&buf),
		Connect: func(_ context.Context, _ string) (listener.Conn, error) {
			return conn, nil
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	// Push three notifications.
	for i := 0; i < 3; i++ {
		conn.notify <- &pgconn.Notification{Channel: listener.Channel, Payload: "run-" + string(rune('A'+i))}
	}

	// Wait until the cache has seen all three clears.
	deadline := time.Now().Add(2 * time.Second)
	for cache.clears.Load() < 3 {
		if time.Now().After(deadline) {
			t.Fatalf("cache clears: got %d want 3 within 2s", cache.clears.Load())
		}
		time.Sleep(2 * time.Millisecond)
	}
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}

	out := buf.String()
	if !strings.Contains(out, `"msg":"listen_connected"`) {
		t.Errorf("logs missing listen_connected: %s", out)
	}
	if !strings.Contains(out, `"msg":"notify_received"`) {
		t.Errorf("logs missing notify_received: %s", out)
	}
	if !strings.Contains(out, `"payload":"run-A"`) {
		t.Errorf("logs missing payload run-A: %s", out)
	}
}

// TestListener_ReconnectsAfterConnectionDrop drives the chaos path with a
// fake Connector that returns a dropping conn on the first call and a
// healthy conn afterwards. The listener must reconnect and resume
// invalidating the cache. Mirrors the integration chaos test without
// needing a real Postgres.
func TestListener_ReconnectsAfterConnectionDrop(t *testing.T) {
	t.Parallel()

	cache := &fakeInvalidator{}
	var buf bytes.Buffer

	droppy := &fakeConn{
		notify:  make(chan *pgconn.Notification),
		dropErr: io.EOF,
	}
	close(droppy.notify) // first wait returns io.EOF immediately

	healthy := &fakeConn{notify: make(chan *pgconn.Notification, 1)}

	var connectCalls atomic.Int64
	l := &listener.Listener{
		DSN:            "ignored",
		Cache:          cache,
		InitialBackoff: 5 * time.Millisecond,
		MaxBackoff:     10 * time.Millisecond,
		Logger:         captureLogger(&buf),
		Connect: func(_ context.Context, _ string) (listener.Conn, error) {
			switch connectCalls.Add(1) {
			case 1:
				return droppy, nil
			default:
				return healthy, nil
			}
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	// Fire a notification after the (eventual) reconnect.
	go func() {
		// Wait until the second connect happened.
		deadline := time.Now().Add(2 * time.Second)
		for connectCalls.Load() < 2 {
			if time.Now().After(deadline) {
				return
			}
			time.Sleep(1 * time.Millisecond)
		}
		healthy.notify <- &pgconn.Notification{Channel: listener.Channel, Payload: "post-reconnect"}
	}()

	deadline := time.Now().Add(3 * time.Second)
	for cache.clears.Load() < 1 {
		if time.Now().After(deadline) {
			t.Fatalf("clears after reconnect: got %d want >=1 (connect_calls=%d, log=%s)",
				cache.clears.Load(), connectCalls.Load(), buf.String())
		}
		time.Sleep(2 * time.Millisecond)
	}
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}

	out := buf.String()
	if !strings.Contains(out, `"msg":"listen_dropped"`) {
		t.Errorf("logs missing listen_dropped: %s", out)
	}
	if !strings.Contains(out, `"msg":"listen_reconnecting"`) {
		t.Errorf("logs missing listen_reconnecting: %s", out)
	}
	if !droppy.closed.Load() {
		t.Errorf("dropped conn not closed before reconnect")
	}
}

// TestListener_BackoffCapsAt30s asserts the cap mandated by the issue.
// Forces every connect to fail so backoff keeps doubling, then inspects
// the slog stream for the highest delay_ms value seen.
func TestListener_BackoffCapsAtMax(t *testing.T) {
	t.Parallel()

	var buf bytes.Buffer
	var connectCalls atomic.Int64
	const maxBackoff = 40 * time.Millisecond

	l := &listener.Listener{
		DSN:            "ignored",
		Cache:          &fakeInvalidator{},
		InitialBackoff: 5 * time.Millisecond,
		MaxBackoff:     maxBackoff,
		Logger:         captureLogger(&buf),
		Connect: func(_ context.Context, _ string) (listener.Conn, error) {
			connectCalls.Add(1)
			return nil, errors.New("connection refused")
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	deadline := time.Now().Add(2 * time.Second)
	for connectCalls.Load() < 6 {
		if time.Now().After(deadline) {
			t.Fatalf("never reached 6 connect attempts: got %d", connectCalls.Load())
		}
		time.Sleep(1 * time.Millisecond)
	}
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}

	// Scan slog lines: every delay_ms must be <= maxBackoff. The doubling
	// schedule starting at 5ms is 5, 10, 20, 40, 40, 40 → cap reached on
	// the 4th attempt.
	maxMs := maxBackoff.Milliseconds()
	for _, line := range strings.Split(buf.String(), "\n") {
		if !strings.Contains(line, `"msg":"listen_reconnecting"`) {
			continue
		}
		// Crude parse — look for "delay_ms":N
		idx := strings.Index(line, `"delay_ms":`)
		if idx < 0 {
			t.Fatalf("listen_reconnecting line missing delay_ms: %s", line)
		}
		var got int64
		tail := line[idx+len(`"delay_ms":`):]
		for i, r := range tail {
			if r < '0' || r > '9' {
				if i == 0 {
					t.Fatalf("bad delay_ms in line: %s", line)
				}
				if _, err := parseInt(tail[:i], &got); err != nil {
					t.Fatalf("parse delay_ms %q: %v", tail[:i], err)
				}
				break
			}
		}
		if got > maxMs {
			t.Errorf("delay_ms %d exceeds max %d (line=%s)", got, maxMs, line)
		}
	}
}

func parseInt(s string, out *int64) (int64, error) {
	var n int64
	for _, r := range s {
		if r < '0' || r > '9' {
			return 0, errors.New("not a digit")
		}
		n = n*10 + int64(r-'0')
	}
	*out = n
	return n, nil
}

// TestListener_NoGoroutineLeakOver100Reconnects asserts the issue's
// goroutine-stability gate: a barrage of force-failed connects must not
// leak the per-iteration goroutines pgx may spawn. We measure
// runtime.NumGoroutine before/after with a small tolerance for scheduler
// noise — the assertion is "no monotonic growth", not zero overhead.
func TestListener_NoGoroutineLeakOver100Reconnects(t *testing.T) {
	t.Parallel()

	var connectCalls atomic.Int64
	var connectLock sync.Mutex

	// First N connects: succeed and drop immediately. Subsequent connects:
	// fail outright. Total = 100 reconnect cycles.
	const cycles = 100

	l := &listener.Listener{
		DSN:            "ignored",
		Cache:          &fakeInvalidator{},
		InitialBackoff: 100 * time.Microsecond,
		MaxBackoff:     200 * time.Microsecond,
		Logger:         slog.New(slog.NewJSONHandler(io.Discard, nil)),
		Connect: func(_ context.Context, _ string) (listener.Conn, error) {
			connectLock.Lock()
			defer connectLock.Unlock()
			connectCalls.Add(1)
			conn := &fakeConn{
				notify:  make(chan *pgconn.Notification),
				dropErr: io.EOF,
			}
			close(conn.notify)
			return conn, nil
		},
	}

	baseline := runtimeNumGoroutines(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()

	deadline := time.Now().Add(5 * time.Second)
	for connectCalls.Load() < cycles {
		if time.Now().After(deadline) {
			t.Fatalf("only %d reconnect cycles in 5s, want %d", connectCalls.Load(), cycles)
		}
		time.Sleep(1 * time.Millisecond)
	}
	cancel()
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}

	// Allow defers/cleanup to settle.
	time.Sleep(50 * time.Millisecond)
	after := runtimeNumGoroutines(t)
	// Tolerance: ±5 goroutines for scheduler/GC noise. The assertion is
	// "did not balloon linearly with cycles" — 100 cycles + a 5-goroutine
	// tolerance catches a per-iteration leak (which would show +100).
	const tolerance = 5
	if after > baseline+tolerance {
		t.Fatalf("goroutine leak: baseline=%d after 100 reconnects=%d (tolerance=%d)",
			baseline, after, tolerance)
	}
}

// TestListener_ContextCancelExitsCleanly proves Run respects ctx
// cancellation during the WaitForNotification sleep.
func TestListener_ContextCancelExitsCleanly(t *testing.T) {
	t.Parallel()

	healthy := &fakeConn{notify: make(chan *pgconn.Notification)}
	l := &listener.Listener{
		DSN:            "ignored",
		Cache:          &fakeInvalidator{},
		InitialBackoff: 5 * time.Millisecond,
		MaxBackoff:     5 * time.Millisecond,
		Logger:         slog.New(slog.NewJSONHandler(io.Discard, nil)),
		Connect: func(_ context.Context, _ string) (listener.Conn, error) {
			return healthy, nil
		},
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- l.Run(ctx) }()
	time.Sleep(20 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Run returned %v, want context.Canceled", err)
		}
	case <-time.After(time.Second):
		t.Fatal("Run did not exit within 1s of cancel")
	}
}
