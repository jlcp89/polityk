package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fakeDimsChecker struct {
	seeded bool
	err    error
}

func (f fakeDimsChecker) DimensionsSeeded(_ context.Context) (bool, error) {
	return f.seeded, f.err
}

type fakeFactsChecker struct {
	ready bool
	err   error
}

func (f fakeFactsChecker) FactsReady(_ context.Context) (bool, error) {
	return f.ready, f.err
}

// fakeHealthInfoReader exercises every branch of the #14 health body without
// touching Postgres. Each field has its own error knob so individual failures
// (Ping vs forecast-query vs scrape-query) can be exercised in isolation.
type fakeHealthInfoReader struct {
	pingErr        error
	lastForecast   *time.Time
	lastForecastE  error
	lastScrape     map[string]*time.Time
	lastScrapeE    error
	scrapesCalled  bool
	scrapeSourcesQ []string
}

func (f *fakeHealthInfoReader) Ping(_ context.Context) error { return f.pingErr }

func (f *fakeHealthInfoReader) LastPublishedForecastAt(_ context.Context) (*time.Time, error) {
	return f.lastForecast, f.lastForecastE
}

func (f *fakeHealthInfoReader) LastScrapeBySource(_ context.Context, sources []string) (map[string]*time.Time, error) {
	f.scrapesCalled = true
	f.scrapeSourcesQ = sources
	return f.lastScrape, f.lastScrapeE
}

func TestHealth_StaticFallback_ReturnsOK(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	Health(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if got, want := body["status"], "ok"; got != want {
		t.Fatalf("status field: got %v want %q", got, want)
	}
	if _, present := body["db_dimensions_seeded"]; present {
		t.Fatalf("db_dimensions_seeded should be omitted when no checker is wired; body=%v", body)
	}
	if _, present := body["db_facts_ready"]; present {
		t.Fatalf("db_facts_ready should be omitted when no checker is wired; body=%v", body)
	}
	if _, present := body["db_connected"]; present {
		t.Fatalf("db_connected should be omitted when no info reader is wired; body=%v", body)
	}
	if _, present := body["last_published_forecast_at"]; present {
		t.Fatalf("last_published_forecast_at should be omitted when no info reader is wired; body=%v", body)
	}
	if _, present := body["last_scrape_by_source"]; present {
		t.Fatalf("last_scrape_by_source should be omitted when no info reader is wired; body=%v", body)
	}
	// blackout_enabled is always emitted: it's an env var read, not a DB hit.
	if _, present := body["blackout_enabled"]; !present {
		t.Fatalf("blackout_enabled must be emitted on every /v1/health response; body=%v", body)
	}
}

func TestHealth_WithDimensionsChecker(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name       string
		checker    DimensionsChecker
		wantSeeded bool
	}{
		{name: "seeded", checker: fakeDimsChecker{seeded: true}, wantSeeded: true},
		{name: "unseeded", checker: fakeDimsChecker{seeded: false}, wantSeeded: false},
		{name: "checker_error_reports_false", checker: fakeDimsChecker{err: errors.New("db down")}, wantSeeded: false},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()

			NewHealth(tt.checker, nil, nil).ServeHTTP(rec, req)

			if got, want := rec.Code, http.StatusOK; got != want {
				t.Fatalf("status: got %d want %d", got, want)
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
			}
			if got, want := body["status"], "ok"; got != want {
				t.Fatalf("status: got %v want %q", got, want)
			}
			got, ok := body["db_dimensions_seeded"].(bool)
			if !ok {
				t.Fatalf("db_dimensions_seeded missing or not a bool; body=%v", body)
			}
			if got != tt.wantSeeded {
				t.Fatalf("db_dimensions_seeded: got %v want %v", got, tt.wantSeeded)
			}
			if _, present := body["db_facts_ready"]; present {
				t.Fatalf("db_facts_ready should be omitted when no facts checker is wired; body=%v", body)
			}
		})
	}
}

func TestHealth_WithFactsChecker(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name      string
		checker   FactsChecker
		wantReady bool
	}{
		{name: "ready", checker: fakeFactsChecker{ready: true}, wantReady: true},
		{name: "not_ready", checker: fakeFactsChecker{ready: false}, wantReady: false},
		{name: "checker_error_reports_false", checker: fakeFactsChecker{err: errors.New("missing table")}, wantReady: false},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()

			NewHealth(nil, tt.checker, nil).ServeHTTP(rec, req)

			if got, want := rec.Code, http.StatusOK; got != want {
				t.Fatalf("status: got %d want %d", got, want)
			}
			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
			}
			got, ok := body["db_facts_ready"].(bool)
			if !ok {
				t.Fatalf("db_facts_ready missing or not a bool; body=%v", body)
			}
			if got != tt.wantReady {
				t.Fatalf("db_facts_ready: got %v want %v", got, tt.wantReady)
			}
		})
	}
}

func TestHealth_WithBothCheckers(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	NewHealth(fakeDimsChecker{seeded: true}, fakeFactsChecker{ready: true}, nil).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if body["db_dimensions_seeded"] != true {
		t.Fatalf("db_dimensions_seeded: got %v want true", body["db_dimensions_seeded"])
	}
	if body["db_facts_ready"] != true {
		t.Fatalf("db_facts_ready: got %v want true", body["db_facts_ready"])
	}
}

// ---------------------------------------------------------------------------
// Issue #14 — rich health body
// ---------------------------------------------------------------------------

func TestHealth_HappyPath_AllFourFields(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "false")

	ts := time.Date(2027, 6, 1, 12, 0, 0, 0, time.UTC)
	tseTS := time.Date(2027, 5, 30, 8, 30, 0, 0, time.UTC)
	rssTS := time.Date(2027, 5, 31, 14, 15, 0, 0, time.UTC)

	info := &fakeHealthInfoReader{
		lastForecast: &ts,
		lastScrape: map[string]*time.Time{
			"tse_party_list": &tseTS,
			"rss_aggregator": &rssTS,
			// memoria_pdf intentionally absent — handler must fill nil.
		},
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	NewHealth(nil, nil, info).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("status: got %v want \"ok\"", body["status"])
	}
	if body["db_connected"] != true {
		t.Errorf("db_connected: got %v want true", body["db_connected"])
	}
	if body["blackout_enabled"] != false {
		t.Errorf("blackout_enabled: got %v want false", body["blackout_enabled"])
	}
	if got, want := body["last_published_forecast_at"], ts.Format(time.RFC3339Nano); got != want {
		t.Errorf("last_published_forecast_at: got %v want %q", got, want)
	}

	scrapes, ok := body["last_scrape_by_source"].(map[string]any)
	if !ok {
		t.Fatalf("last_scrape_by_source missing or not an object; body=%v", body)
	}
	wantTSE := tseTS.Format(time.RFC3339Nano)
	if scrapes["tse_party_list"] != wantTSE {
		t.Errorf("scrape[tse_party_list]: got %v want %q", scrapes["tse_party_list"], wantTSE)
	}
	wantRSS := rssTS.Format(time.RFC3339Nano)
	if scrapes["rss_aggregator"] != wantRSS {
		t.Errorf("scrape[rss_aggregator]: got %v want %q", scrapes["rss_aggregator"], wantRSS)
	}
	// memoria_pdf must still be present, as JSON null.
	mem, present := scrapes["memoria_pdf"]
	if !present {
		t.Errorf("scrape[memoria_pdf]: missing key; want present-with-null")
	}
	if mem != nil {
		t.Errorf("scrape[memoria_pdf]: got %v want null", mem)
	}

	// The handler must request exactly the three documented sources, in the
	// fixed order. Any drift would break the Android client's expected shape.
	wantSources := []string{"tse_party_list", "rss_aggregator", "memoria_pdf"}
	if len(info.scrapeSourcesQ) != len(wantSources) {
		t.Fatalf("scrape sources requested: got %v want %v", info.scrapeSourcesQ, wantSources)
	}
	for i, s := range wantSources {
		if info.scrapeSourcesQ[i] != s {
			t.Errorf("scrape sources[%d]: got %q want %q", i, info.scrapeSourcesQ[i], s)
		}
	}
}

func TestHealth_NoForecastAndNoScrapes_FieldsAreNull(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "false")

	info := &fakeHealthInfoReader{
		lastForecast: nil,
		lastScrape:   map[string]*time.Time{},
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	NewHealth(nil, nil, info).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if _, present := body["last_published_forecast_at"]; !present {
		t.Errorf("last_published_forecast_at should always be present (as null); body=%v", body)
	}
	if v := body["last_published_forecast_at"]; v != nil {
		t.Errorf("last_published_forecast_at: got %v want null", v)
	}

	scrapes, ok := body["last_scrape_by_source"].(map[string]any)
	if !ok {
		t.Fatalf("last_scrape_by_source missing or not an object; body=%v", body)
	}
	for _, s := range HealthScrapeSources {
		v, present := scrapes[s]
		if !present {
			t.Errorf("scrape[%s]: missing key; want present-with-null", s)
		}
		if v != nil {
			t.Errorf("scrape[%s]: got %v want null", s, v)
		}
	}
}

func TestHealth_DBUnreachable_Returns503Degraded(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "false")

	info := &fakeHealthInfoReader{
		pingErr: errors.New("connection refused"),
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()

	NewHealth(nil, nil, info).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	ct := rec.Header().Get("Content-Type")
	if !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if body["status"] != "degraded" {
		t.Errorf("status: got %v want \"degraded\"", body["status"])
	}
	if body["db_connected"] != false {
		t.Errorf("db_connected: got %v want false", body["db_connected"])
	}
	if body["blackout_enabled"] != false {
		t.Errorf("blackout_enabled: got %v want false", body["blackout_enabled"])
	}

	// When the DB is unreachable the handler must NOT have walked the other
	// queries — Ping is the single short-circuit gate.
	if info.scrapesCalled {
		t.Errorf("LastScrapeBySource was called after Ping failed; want short-circuit")
	}
}

func TestHealth_BlackoutEnvVar(t *testing.T) {
	cases := []struct {
		envValue string
		want     bool
	}{
		{envValue: "", want: false},
		{envValue: "false", want: false},
		{envValue: "FALSE", want: false},
		{envValue: "0", want: false},
		{envValue: "garbage", want: false},
		{envValue: "true", want: true},
		{envValue: "TRUE", want: true},
		{envValue: "True", want: true},
		{envValue: "1", want: true},
		{envValue: "t", want: true},
		{envValue: "T", want: true},
	}
	for _, c := range cases {
		c := c
		t.Run(c.envValue, func(t *testing.T) {
			t.Setenv("BLACKOUT_ENABLED", c.envValue)

			req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
			rec := httptest.NewRecorder()
			NewHealth(nil, nil, nil).ServeHTTP(rec, req)

			var body map[string]any
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v", err)
			}
			if body["blackout_enabled"] != c.want {
				t.Errorf("blackout_enabled for env=%q: got %v want %v",
					c.envValue, body["blackout_enabled"], c.want)
			}
		})
	}
}

// TestHealth_PerFieldDBErrorDoesNotTrip503 pins the contract: if Ping succeeds
// but a follow-up per-field query fails (e.g. forecasts table is missing),
// the handler stays at 200 and the failing field is reported as null.
func TestHealth_PerFieldDBErrorDoesNotTrip503(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "false")

	info := &fakeHealthInfoReader{
		lastForecastE: errors.New("relation \"forecasts\" does not exist"),
		lastScrapeE:   errors.New("relation \"scrape_runs\" does not exist"),
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()
	NewHealth(nil, nil, info).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d (per-field errors must not trip 503)", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["db_connected"] != true {
		t.Errorf("db_connected: got %v want true (Ping succeeded)", body["db_connected"])
	}
	if v := body["last_published_forecast_at"]; v != nil {
		t.Errorf("last_published_forecast_at: got %v want null on query error", v)
	}
	scrapes, ok := body["last_scrape_by_source"].(map[string]any)
	if !ok {
		t.Fatalf("last_scrape_by_source missing or not an object; body=%v", body)
	}
	for _, s := range HealthScrapeSources {
		if scrapes[s] != nil {
			t.Errorf("scrape[%s]: got %v want null on query error", s, scrapes[s])
		}
	}
}

// TestHealth_FullCompositionMirrorsIssueExample asserts the full JSON shape
// the issue body documents, with all three readers wired.
func TestHealth_FullCompositionMirrorsIssueExample(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "true")

	ts := time.Date(2027, 6, 1, 12, 0, 0, 0, time.UTC)
	memTS := time.Date(2027, 4, 1, 9, 0, 0, 0, time.UTC)
	info := &fakeHealthInfoReader{
		lastForecast: &ts,
		lastScrape: map[string]*time.Time{
			"memoria_pdf": &memTS,
		},
	}
	dims := fakeDimsChecker{seeded: true}
	facts := fakeFactsChecker{ready: true}

	req := httptest.NewRequest(http.MethodGet, "/v1/health", nil)
	rec := httptest.NewRecorder()
	NewHealth(dims, facts, info).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	wantFields := []string{
		"status", "db_connected", "blackout_enabled",
		"last_published_forecast_at", "last_scrape_by_source",
		"db_dimensions_seeded", "db_facts_ready",
	}
	for _, f := range wantFields {
		if _, present := body[f]; !present {
			t.Errorf("missing field %q in body=%v", f, body)
		}
	}
	if body["blackout_enabled"] != true {
		t.Errorf("blackout_enabled: got %v want true", body["blackout_enabled"])
	}
}
