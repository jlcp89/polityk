package handlers_test

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/middleware"
)

type fakePollsterBiasReader struct {
	priors []handlers.PollsterBiasPrior
	err    error
}

func (f fakePollsterBiasReader) PollsterBiasPriors(_ context.Context) ([]handlers.PollsterBiasPrior, error) {
	return f.priors, f.err
}

func newMethodologyHandler(reader handlers.PollsterBiasReader) http.Handler {
	return handlers.NewMethodology(reader, handlers.DefaultMethodologyConfig())
}

// TestMethodology_HappyPath_ReturnsDocumentedShape pins the JSON shape from
// the issue body. Every documented field must be present and the pollster
// priors must reflect the reader output 1:1.
func TestMethodology_HappyPath_ReturnsDocumentedShape(t *testing.T) {
	t.Parallel()

	reader := fakePollsterBiasReader{priors: []handlers.PollsterBiasPrior{
		{Pollster: "ProDatos", HistoricalBiasMean: 0.0, HistoricalBiasSD: 0.05, SampleCountUsed: 0},
		{Pollster: "CID Gallup", HistoricalBiasMean: 0.01, HistoricalBiasSD: 0.08, SampleCountUsed: 12},
	}}

	req := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	rec := httptest.NewRecorder()
	newMethodologyHandler(reader).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("content-type: got %q want application/json prefix", ct)
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "public, max-age=3600" {
		t.Fatalf("cache-control: got %q want %q", cc, "public, max-age=3600")
	}

	var body struct {
		ModelVersion string `json:"model_version"`
		GeneratedAt  string `json:"generated_at"`
		Presidential struct {
			PollsterBiasPriors []struct {
				Pollster           string  `json:"pollster"`
				HistoricalBiasMean float64 `json:"historical_bias_mean"`
				HistoricalBiasSD   float64 `json:"historical_bias_sd"`
				SampleCountUsed    int     `json:"sample_count_used"`
			} `json:"pollster_bias_priors"`
			FundamentalsFeatures     []string           `json:"fundamentals_features"`
			SentimentAsModelledInput bool               `json:"sentiment_as_modelled_input"`
			CalibrationThresholds    map[string]float64 `json:"calibration_thresholds"`
		} `json:"presidential"`
		LongFormURL string `json:"long_form_url"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}

	if body.ModelVersion != "0.1.0" {
		t.Errorf("model_version: got %q want %q", body.ModelVersion, "0.1.0")
	}
	if _, err := time.Parse(time.RFC3339, body.GeneratedAt); err != nil {
		t.Errorf("generated_at not RFC3339: %q (%v)", body.GeneratedAt, err)
	}
	if len(body.Presidential.PollsterBiasPriors) != 2 {
		t.Fatalf("pollster_bias_priors length: got %d want 2", len(body.Presidential.PollsterBiasPriors))
	}
	prodatos := body.Presidential.PollsterBiasPriors[0]
	if prodatos.Pollster != "ProDatos" || prodatos.HistoricalBiasSD != 0.05 || prodatos.SampleCountUsed != 0 {
		t.Errorf("ProDatos prior mismatch: %+v", prodatos)
	}
	cid := body.Presidential.PollsterBiasPriors[1]
	if cid.Pollster != "CID Gallup" || cid.HistoricalBiasMean != 0.01 || cid.HistoricalBiasSD != 0.08 || cid.SampleCountUsed != 12 {
		t.Errorf("CID Gallup prior mismatch: %+v", cid)
	}

	for _, want := range []string{
		"incumbent_party", "gdp_growth_yoy", "inflation_yoy", "sentiment_trend",
	} {
		if !contains(body.Presidential.FundamentalsFeatures, want) {
			t.Errorf("fundamentals_features missing %q (got %v)", want, body.Presidential.FundamentalsFeatures)
		}
	}

	for _, want := range []string{"c1_80pct_coverage", "c2_95pct_coverage", "c3_top3_mae_pp"} {
		if _, ok := body.Presidential.CalibrationThresholds[want]; !ok {
			t.Errorf("calibration_thresholds missing %q (got %v)", want, body.Presidential.CalibrationThresholds)
		}
	}
	if body.Presidential.CalibrationThresholds["c1_80pct_coverage"] != 0.80 {
		t.Errorf("c1_80pct_coverage: got %v want 0.80", body.Presidential.CalibrationThresholds["c1_80pct_coverage"])
	}
	if body.Presidential.CalibrationThresholds["c2_95pct_coverage"] != 0.95 {
		t.Errorf("c2_95pct_coverage: got %v want 0.95", body.Presidential.CalibrationThresholds["c2_95pct_coverage"])
	}
	if body.Presidential.CalibrationThresholds["c3_top3_mae_pp"] != 5.0 {
		t.Errorf("c3_top3_mae_pp: got %v want 5.0", body.Presidential.CalibrationThresholds["c3_top3_mae_pp"])
	}

	if body.LongFormURL == "" {
		t.Errorf("long_form_url empty")
	}
}

// TestMethodology_NotGatedByBlackout mirrors production wiring: methodology
// must respond even when BLACKOUT_ENABLED=true. ADR-003 only suppresses
// /v1/forecast/*; methodology disclosure stays live during silencio
// electoral so citizens can audit *why* the forecast is suspended.
func TestMethodology_NotGatedByBlackout(t *testing.T) {
	t.Setenv("BLACKOUT_ENABLED", "true")

	reader := fakePollsterBiasReader{priors: []handlers.PollsterBiasPrior{
		{Pollster: "ProDatos", HistoricalBiasSD: 0.05},
	}}

	root := http.NewServeMux()
	root.Handle("GET /v1/methodology", newMethodologyHandler(reader))

	// Mount a separate blackout-gated forecast sub-mux to prove the
	// methodology route lives OUTSIDE the gate even when both coexist
	// in the same root mux (production wiring in cmd/api/main.go).
	forecastMux := http.NewServeMux()
	forecastMux.HandleFunc("GET /v1/forecast/presidential", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	root.Handle("/v1/forecast/", middleware.Blackout(forecastMux))

	// Forecast route IS blackout-gated.
	forecastReq := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	forecastRec := httptest.NewRecorder()
	root.ServeHTTP(forecastRec, forecastReq)
	if forecastRec.Code != http.StatusServiceUnavailable {
		t.Fatalf("blackout did not gate forecast: got %d want 503", forecastRec.Code)
	}

	// Methodology route is NOT.
	methReq := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	methRec := httptest.NewRecorder()
	root.ServeHTTP(methRec, methReq)
	if methRec.Code != http.StatusOK {
		t.Fatalf("methodology returned %d during blackout (body=%q); must be 200", methRec.Code, methRec.Body.String())
	}
	if !strings.Contains(methRec.Body.String(), "pollster_bias_priors") {
		t.Errorf("methodology body missing pollster_bias_priors during blackout: %q", methRec.Body.String())
	}
	if strings.Contains(methRec.Body.String(), `"error":"blackout"`) {
		t.Errorf("methodology leaked blackout error body: %q", methRec.Body.String())
	}
}

func TestMethodology_NilReader_Returns503(t *testing.T) {
	t.Parallel()

	req := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	rec := httptest.NewRecorder()
	newMethodologyHandler(nil).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if body["error"] != "db_unavailable" {
		t.Errorf("error: got %q want %q", body["error"], "db_unavailable")
	}
	// Cache-Control + Content-Type set even on error so cdn/proxy
	// behaviour stays consistent.
	if cc := rec.Header().Get("Cache-Control"); cc != "public, max-age=3600" {
		t.Errorf("cache-control on 503: got %q want %q", cc, "public, max-age=3600")
	}
}

func TestMethodology_ReaderError_Returns500(t *testing.T) {
	t.Parallel()

	reader := fakePollsterBiasReader{err: errors.New("connection refused")}

	req := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	rec := httptest.NewRecorder()
	newMethodologyHandler(reader).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusInternalServerError; got != want {
		t.Fatalf("status: got %d want %d (body=%q)", got, want, rec.Body.String())
	}
}

// TestMethodology_EmptyPollsters_StillReturnsDocumentedShape asserts that a
// pre-seed boot (zero rows in pollsters) does not error — the field becomes
// an empty array, not null.
func TestMethodology_EmptyPollsters_StillReturnsDocumentedShape(t *testing.T) {
	t.Parallel()

	reader := fakePollsterBiasReader{priors: nil}

	req := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	rec := httptest.NewRecorder()
	newMethodologyHandler(reader).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status: got %d want 200 (body=%q)", rec.Code, rec.Body.String())
	}
	// Match `"pollster_bias_priors":[]` literally — a `null` here would
	// break the Android Moshi adapter expecting a list type.
	if !strings.Contains(rec.Body.String(), `"pollster_bias_priors":[]`) {
		t.Errorf("expected empty array literal, got body: %q", rec.Body.String())
	}
}

func contains(haystack []string, needle string) bool {
	for _, s := range haystack {
		if s == needle {
			return true
		}
	}
	return false
}
