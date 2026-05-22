// Command blackout is the manual override CLI for the legal-blackout flag
// (issue #46, ADR-003).
//
//	blackout enable  --reason "..." [--operator <name>]
//	blackout disable --reason "..." [--operator <name>]
//	blackout status
//
// `enable`/`disable` write "true"/"false" to BLACKOUT_FLAG_FILE (the path the
// Go API middleware reads on every request) and insert a row into
// blackout_overrides. `status` reads the effective flag and the last 5
// audit rows. Operators run this as a backup to the systemd timers when DST
// or clock skew creates a discrepancy between the legal schedule and the
// API's served state.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/jlcp89/polityk/internal/blackoutcli"
)

func main() {
	os.Exit(realMain())
}

func realMain() int {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	opts := blackoutcli.Options{
		Args:     os.Args[1:],
		Stdout:   os.Stdout,
		Stderr:   os.Stderr,
		Stdin:    os.Stdin,
		FlagFile: os.Getenv(blackoutcli.EnvFlagFile),
		EnvFlag:  os.Getenv(blackoutcli.EnvBlackoutEnabled),
		UserEnv:  os.Getenv("USER"),
		Now:      time.Now,
	}

	if dsn := os.Getenv("DATABASE_URL"); dsn != "" {
		db, err := sql.Open("pgx", dsn)
		if err != nil {
			fmt.Fprintf(os.Stderr, "blackout: open DATABASE_URL: %v\n", err)
			return 1
		}
		defer func() {
			if cerr := db.Close(); cerr != nil {
				logger.Warn("db_close_failed", "err", cerr)
			}
		}()
		audit := &blackoutcli.SQLAudit{DB: db}
		opts.Writer = audit
		opts.Reader = audit
	}

	if err := blackoutcli.Run(ctx, opts); err != nil {
		if errors.Is(err, blackoutcli.ErrUsage) {
			return 2
		}
		fmt.Fprintf(os.Stderr, "blackout: %v\n", err)
		return 1
	}
	return 0
}
