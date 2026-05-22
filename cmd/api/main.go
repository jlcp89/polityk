// Command api serves the polityk JSON HTTP API.
//
// v1 scaffolding (issue #1): wires net/http + log/slog and a static
// /v1/health endpoint. No database is required to start the server —
// real health checks land in issue #14.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/middleware"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	addr := os.Getenv("POLITYK_API_ADDR")
	if addr == "" {
		addr = ":8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/health", handlers.Health)

	// Forecast routes are blackout-gated per ADR-003. Handlers registered
	// on forecastMux automatically inherit the 503 short-circuit when
	// BLACKOUT_ENABLED flips on. Issue #9 registers the first real route.
	forecastMux := http.NewServeMux()
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
