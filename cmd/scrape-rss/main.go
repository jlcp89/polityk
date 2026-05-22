// Command scrape-rss runs the RSS aggregator (internal/scrapers/rss) once
// against the live outlets in docs/requirement.md Section B and writes
// fetched articles to news_articles. Stamps scrape_runs on completion.
//
// Usage: DATABASE_URL=postgres://... scrape-rss
package main

import (
	"context"
	"database/sql"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/jlcp89/polityk/internal/scrapers/rss"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		logger.Error("DATABASE_URL is required")
		os.Exit(2)
	}

	db, err := sql.Open("pgx", dsn)
	if err != nil {
		logger.Error("db_open_failed", "err", err)
		os.Exit(1)
	}
	defer func() {
		if cerr := db.Close(); cerr != nil {
			logger.Warn("db_close_failed", "err", cerr)
		}
	}()

	if perr := db.Ping(); perr != nil {
		logger.Error("db_ping_failed", "err", perr)
		os.Exit(1)
	}

	ctx, cancel := signal.NotifyContext(context.Background(),
		syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// Cap the whole run so a wedged outlet can't hang the process indefinitely.
	ctx, cancelTimeout := context.WithTimeout(ctx, 15*time.Minute)
	defer cancelTimeout()

	logger.Info("rss_run_start")
	if rerr := rss.Run(ctx, db); rerr != nil {
		logger.Error("rss_run_failed", "err", rerr)
		os.Exit(1)
	}
	logger.Info("rss_run_done")
}
