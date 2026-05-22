// Package handlers contains the HTTP handlers for the polityk API.
package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"time"
)

// DimensionsChecker reports whether the dimension tables have been seeded.
// "Seeded" is `geographies` having at least one row.
type DimensionsChecker interface {
	DimensionsSeeded(ctx context.Context) (bool, error)
}

// FactsChecker reports whether the race-specific fact tables exist.
type FactsChecker interface {
	FactsReady(ctx context.Context) (bool, error)
}

// HealthInfoReader produces the rich `/v1/health` body defined by issue #14:
// DB connectivity (Ping), the latest published-forecast timestamp, and the
// per-source last-scrape timestamps. Implementations live in internal/store;
// tests pass fakes. Nil disables every #14 field (handler keeps returning the
// static {status:ok} envelope plus the dims/facts fields when those checkers
// are wired).
type HealthInfoReader interface {
	Ping(ctx context.Context) error
	LastPublishedForecastAt(ctx context.Context) (*time.Time, error)
	LastScrapeBySource(ctx context.Context, sources []string) (map[string]*time.Time, error)
}

// healthBlackoutEnvVar is the env var the handler reads to populate the
// `blackout_enabled` field. Identical contract to internal/middleware.Blackout
// (strconv.ParseBool — only 1/t/T/TRUE/true/True flips it on). Read fresh
// per request so a systemd-timer or override-CLI flip (#46) shows up on the
// very next /v1/health.
const healthBlackoutEnvVar = "BLACKOUT_ENABLED"

// HealthScrapeSources are the per-source keys reported in `last_scrape_by_source`.
// Exact set fixed by the issue body. Every key is always present in the response
// (null when no row exists in scrape_runs) so the Android client can render a
// stable shape.
var HealthScrapeSources = []string{
	"tse_party_list", // #15 — internal/scrapers/tse SourcePartyList
	"rss_aggregator", // #16 — internal/scrapers/rss SourceRSSAggregator
	"memoria_pdf",    // #20-#22 — Memoria Electoral loaders (planned)
}

// NewHealth returns the /v1/health handler. All three readers are optional —
// any nil arg simply omits the corresponding field set, which lets the API
// boot before Postgres is wired (contributor workflow) and lets tests cherry-
// pick which checkers they exercise.
//
// When `info` is non-nil the handler short-circuits to 503 with
// `{status:"degraded", db_connected:false, blackout_enabled:<flag>}` whenever
// info.Ping fails. Per-field DB errors (e.g. a missing forecasts table because
// migration 0006 hasn't been applied yet) are logged as warnings and degrade
// to `null` rather than tripping the 503 — Ping is the single source of truth
// for the connectivity flag.
func NewHealth(dims DimensionsChecker, facts FactsChecker, info HealthInfoReader) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if info != nil {
			if err := info.Ping(r.Context()); err != nil {
				slog.Warn("health_db_ping_failed", "err", err)
				writeDegraded(w)
				return
			}
		}

		body := map[string]any{"status": "ok"}
		if info != nil {
			body["db_connected"] = true
			body["last_published_forecast_at"] = lookupLastPublishedForecastAt(r.Context(), info)
			body["last_scrape_by_source"] = lookupLastScrapeBySource(r.Context(), info)
		}
		body["blackout_enabled"] = healthBlackoutEnabled()
		if dims != nil {
			body["db_dimensions_seeded"] = lookupDimensionsSeeded(r.Context(), dims)
		}
		if facts != nil {
			body["db_facts_ready"] = lookupFactsReady(r.Context(), facts)
		}

		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		if err := json.NewEncoder(w).Encode(body); err != nil {
			slog.Error("health_encode_failed", "err", err)
		}
	}
}

// Health is the static fallback handler used when no DB checker is wired.
// Kept exported for callers that still reference it directly.
func Health(w http.ResponseWriter, r *http.Request) {
	NewHealth(nil, nil, nil).ServeHTTP(w, r)
}

func writeDegraded(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusServiceUnavailable)
	body := map[string]any{
		"status":           "degraded",
		"db_connected":     false,
		"blackout_enabled": healthBlackoutEnabled(),
	}
	if err := json.NewEncoder(w).Encode(body); err != nil {
		slog.Error("health_degraded_encode_failed", "err", err)
	}
}

func healthBlackoutEnabled() bool {
	v, err := strconv.ParseBool(os.Getenv(healthBlackoutEnvVar))
	if err != nil {
		return false
	}
	return v
}

func lookupLastPublishedForecastAt(ctx context.Context, info HealthInfoReader) *time.Time {
	ts, err := info.LastPublishedForecastAt(ctx)
	if err != nil {
		slog.Warn("health_last_forecast_lookup_failed", "err", err)
		return nil
	}
	return ts
}

func lookupLastScrapeBySource(ctx context.Context, info HealthInfoReader) map[string]*time.Time {
	out := make(map[string]*time.Time, len(HealthScrapeSources))
	for _, s := range HealthScrapeSources {
		out[s] = nil
	}
	got, err := info.LastScrapeBySource(ctx, HealthScrapeSources)
	if err != nil {
		slog.Warn("health_scrape_runs_lookup_failed", "err", err)
		return out
	}
	for _, s := range HealthScrapeSources {
		if ts, ok := got[s]; ok {
			out[s] = ts
		}
	}
	return out
}

func lookupDimensionsSeeded(ctx context.Context, dims DimensionsChecker) bool {
	seeded, err := dims.DimensionsSeeded(ctx)
	if err != nil {
		slog.Warn("health_dimensions_check_failed", "err", err)
		return false
	}
	return seeded
}

func lookupFactsReady(ctx context.Context, facts FactsChecker) bool {
	ready, err := facts.FactsReady(ctx)
	if err != nil {
		slog.Warn("health_facts_check_failed", "err", err)
		return false
	}
	return ready
}
