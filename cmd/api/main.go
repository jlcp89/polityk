// Command api serves the polityk JSON HTTP API.
//
// v1 scaffolding (issue #1, extended in #2): wires net/http + log/slog and
// the /v1/health endpoint. When DATABASE_URL is set the health endpoint
// also reports `db_dimensions_seeded`. When it isn't set, the API still
// starts so contributors can run it without Postgres in the loop.
package main

import (
	"context"
	"database/sql"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/middleware"
	"github.com/jlcp89/polityk/internal/store"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	addr := os.Getenv("POLITYK_API_ADDR")
	if addr == "" {
		addr = ":8080"
	}

	var dims handlers.DimensionsChecker
	var facts handlers.FactsChecker
	var forecasts handlers.ForecastReader
	if dsn := os.Getenv("DATABASE_URL"); dsn != "" {
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
		dims = &store.DimensionsChecker{DB: db}
		facts = &store.FactsChecker{DB: db}
		forecasts = &store.ForecastReader{DB: db}
		logger.Info("db_connected")
	} else {
		logger.Info("db_skipped_no_dsn")
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", handlers.NewHealth(dims, facts))

	// Forecast routes are blackout-gated per ADR-003. Handlers registered
	// on forecastMux automatically inherit the 503 short-circuit when
	// BLACKOUT_ENABLED flips on. Issue #9 registers the first real route.
	forecastMux := http.NewServeMux()
	forecastMux.HandleFunc("GET /v1/forecast/presidential", handlers.NewPresidentialForecast(forecasts))
	mux.Handle("/v1/forecast/", middleware.Blackout(forecastMux))

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	idleClosed := make(chan struct{})
	go func() {
		sigs := make(chan os.Signal, 1)
		signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
		<-sigs
		logger.Info("shutdown_signal_received")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			logger.Error("shutdown_failed", "err", err)
		}
		close(idleClosed)
	}()

	logger.Info("server_starting", "addr", addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.Error("server_failed", "err", err)
		os.Exit(1)
	}
	<-idleClosed
	logger.Info("server_stopped")
}
