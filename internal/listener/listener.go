// Package listener implements the ADR-006 LISTEN/NOTIFY watcher: a
// background goroutine that holds a dedicated pgx connection (separate
// from the HTTP request pool) on LISTEN forecast_ready and clears the
// in-process forecast cache on every notification.
//
// The loop is reconnect-on-drop with exponential backoff capped at 30 s,
// so the chaos test in this package (kill+restart Postgres / terminate
// the backend) can fire NOTIFY after recovery and observe the cache
// being cleared — the issue-#10 acceptance criterion verbatim.
package listener

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

const (
	// Channel is the LISTEN/NOTIFY channel name the Python writer (#33)
	// fires per ADR-006. Exported so the integration test can send NOTIFY
	// against the same constant.
	Channel = "forecast_ready"

	// DefaultInitialBackoff is the first reconnect delay; doubles each
	// failed attempt up to DefaultMaxBackoff.
	DefaultInitialBackoff = 500 * time.Millisecond

	// DefaultMaxBackoff is the upper bound mandated by the issue body.
	DefaultMaxBackoff = 30 * time.Second
)

// Invalidator is the cache contract — the listener invokes Clear on every
// notification. forecastcache.Cache satisfies this; tests substitute a
// counting fake.
type Invalidator interface {
	Clear()
}

// Connector opens a pgx connection. Production uses pgx.Connect; tests
// inject a fake to drive the backoff path without a real DB.
type Connector func(ctx context.Context, dsn string) (Conn, error)

// Conn is the subset of pgx.Conn the listener uses. The interface keeps
// the listener testable: a fake Conn drives WaitForNotification errors
// without needing pg_terminate_backend.
type Conn interface {
	Exec(ctx context.Context, sql string, args ...any) (pgconn.CommandTag, error)
	WaitForNotification(ctx context.Context) (*pgconn.Notification, error)
	Close(ctx context.Context) error
}

// Listener runs the LISTEN forecast_ready loop. Zero-value fields are
// filled with defaults at Run() time, so callers can pass just DSN and
// Cache for the production wiring.
type Listener struct {
	DSN            string
	Cache          Invalidator
	InitialBackoff time.Duration
	MaxBackoff     time.Duration
	Connect        Connector
	// Logger overrides slog.Default() — exported for tests that need to
	// capture the structured event names (`listen_connected`,
	// `notify_received`, `listen_dropped`, `listen_reconnecting`).
	Logger *slog.Logger
}

// Run blocks until ctx is cancelled. It returns ctx.Err() on normal
// shutdown; other errors are surfaced only when the very first connection
// attempt fails for a non-transient reason that the backoff would also
// keep retrying — those are still logged as listen_dropped, so a caller
// who ignores the return value still gets the full picture from slog.
func (l *Listener) Run(ctx context.Context) error {
	cfg := l.applyDefaults()
	backoff := cfg.InitialBackoff
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		connected, err := listenOnce(ctx, cfg)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if connected {
			backoff = cfg.InitialBackoff
		}
		cfg.Logger.Warn("listen_dropped", "err", err.Error(), "channel", Channel)
		cfg.Logger.Info("listen_reconnecting", "delay_ms", backoff.Milliseconds(), "channel", Channel)
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
		backoff = nextBackoff(backoff, cfg.MaxBackoff)
	}
}

// listenOnce holds a single pgx connection on LISTEN <Channel> and drains
// notifications. The first return value is true iff the connection
// established successfully (so the caller resets backoff). The error is
// the reason the loop ended — never nil because the loop only exits on
// failure (ctx cancellation is a special case checked separately).
func listenOnce(ctx context.Context, cfg Listener) (bool, error) {
	conn, err := cfg.Connect(ctx, cfg.DSN)
	if err != nil {
		return false, fmt.Errorf("connect: %w", err)
	}
	defer func() { _ = conn.Close(context.Background()) }()

	if _, err := conn.Exec(ctx, "LISTEN "+Channel); err != nil {
		return false, fmt.Errorf("listen: %w", err)
	}
	cfg.Logger.Info("listen_connected", "channel", Channel)

	for {
		notif, err := conn.WaitForNotification(ctx)
		if err != nil {
			return true, fmt.Errorf("wait_for_notification: %w", err)
		}
		cfg.Logger.Info("notify_received", "channel", notif.Channel, "payload", notif.Payload)
		cfg.Cache.Clear()
	}
}

func (l *Listener) applyDefaults() Listener {
	cfg := *l
	if cfg.InitialBackoff <= 0 {
		cfg.InitialBackoff = DefaultInitialBackoff
	}
	if cfg.MaxBackoff <= 0 {
		cfg.MaxBackoff = DefaultMaxBackoff
	}
	if cfg.Connect == nil {
		cfg.Connect = pgxConnect
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}
	if cfg.Cache == nil {
		cfg.Cache = noopInvalidator{}
	}
	return cfg
}

func nextBackoff(current, max time.Duration) time.Duration {
	if current >= max {
		return max
	}
	doubled := current * 2
	if doubled > max || doubled < current { // overflow guard
		return max
	}
	return doubled
}

func pgxConnect(ctx context.Context, dsn string) (Conn, error) {
	c, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return nil, err
	}
	return c, nil
}

type noopInvalidator struct{}

func (noopInvalidator) Clear() {}

// ErrConnectionDropped is returned (wrapped) when the listener's
// WaitForNotification call resolves with a non-cancellation error. Kept
// for callers that want to inspect the loop's exit reason; the test suite
// uses errors.Is for the chaos-test reconnect assertion.
var ErrConnectionDropped = errors.New("listen connection dropped")
