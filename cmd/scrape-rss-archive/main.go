// Command scrape-rss-archive backfills news_articles from Internet
// Archive (Wayback Machine) snapshots of each outlet's historical RSS
// feed. Sample ~8 snapshots per outlet per Guatemalan campaign window
// (2019 + 2023) by default; tune via flags. Articles are deduplicated
// against the existing news_articles by URL.
//
// Usage: DATABASE_URL=postgres://... scrape-rss-archive
package main

import (
	"context"
	"database/sql"
	"flag"
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

	samplesPerWindow := flag.Int("samples", 8,
		"approximate number of snapshots to fetch per outlet per window")
	timeoutMin := flag.Int("timeout-min", 30,
		"hard cap on the whole run in minutes")
	flag.Parse()

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
	ctx, cancelT := context.WithTimeout(ctx, time.Duration(*timeoutMin)*time.Minute)
	defer cancelT()

	client := rss.NewDefaultArchiveClient()
	// Apply per-run sample override.
	windows := client.Windows
	for i := range windows {
		windows[i].Samples = *samplesPerWindow
	}
	client.Windows = windows

	logger.Info("rss_archive_run_start",
		"samples_per_window", *samplesPerWindow,
		"outlets", len(client.Outlets),
		"windows", len(client.Windows))
	if rerr := client.Run(ctx, db); rerr != nil {
		logger.Error("rss_archive_run_failed", "err", rerr)
		os.Exit(1)
	}
	logger.Info("rss_archive_run_done")
}
