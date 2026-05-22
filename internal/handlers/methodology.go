package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

// PollsterBiasPrior is one row of the `pollsters` table projected for the
// /v1/methodology response. The four fields match ADR-017's accepted columns
// (name + the historical-bias triple). `bias_last_estimated_at` is excluded
// from the public payload to keep the methodology shape minimal — anyone
// digging deeper hits the long-form methodology URL.
type PollsterBiasPrior struct {
	Pollster           string  `json:"pollster"`
	HistoricalBiasMean float64 `json:"historical_bias_mean"`
	HistoricalBiasSD   float64 `json:"historical_bias_sd"`
	SampleCountUsed    int     `json:"sample_count_used"`
}

// PollsterBiasReader fetches the bias-prior rows that the methodology
// endpoint exposes verbatim. Returning an empty slice is valid — pre-seed
// boots and tests rely on it.
type PollsterBiasReader interface {
	PollsterBiasPriors(ctx context.Context) ([]PollsterBiasPrior, error)
}

// MethodologyConfig pins the non-pollster fields that ADR-014 documents on
// the /v1/methodology shape. Values are constants for v1; #38 will flip
// SentimentAsModelledInput at fit time from a config row once the
// calibration gate exists.
type MethodologyConfig struct {
	ModelVersion             string
	FundamentalsFeatures     []string
	SentimentAsModelledInput bool
	CalibrationThresholds    map[string]float64
	LongFormURL              string
}

// DefaultMethodologyConfig returns the v1 launch values. The fundamentals
// feature list mirrors issue #31; the calibration thresholds mirror ADR-013
// gates C1/C2/C3.
func DefaultMethodologyConfig() MethodologyConfig {
	return MethodologyConfig{
		ModelVersion: "0.1.0",
		FundamentalsFeatures: []string{
			"incumbent_party",
			"party_of_government_penalty",
			"gdp_growth_yoy",
			"inflation_yoy",
			"remittance_growth_yoy",
			"homicide_rate_change_yoy",
			"sentiment_trend",
			"polling_environment",
		},
		SentimentAsModelledInput: true,
		CalibrationThresholds: map[string]float64{
			"c1_80pct_coverage": 0.80,
			"c2_95pct_coverage": 0.95,
			"c3_top3_mae_pp":    5.0,
		},
		LongFormURL: "https://polityk.gt/methodology#presidential-0.1.0",
	}
}

// NewMethodology returns the `GET /v1/methodology` handler.
//
// Per ADR-014 + ADR-017, the response document is:
//
//	{ "model_version", "generated_at",
//	  "presidential": {
//	    "pollster_bias_priors": [...live from pollsters table...],
//	    "fundamentals_features": [...],
//	    "sentiment_as_modelled_input": bool,
//	    "calibration_thresholds": { c1, c2, c3 }
//	  },
//	  "long_form_url" }
//
// The endpoint is NOT mounted under the blackout middleware in main.go —
// methodology disclosure stays available during the silencio electoral so
// citizens can audit the methodology while the forecast is suppressed.
// `Cache-Control: public, max-age=3600` per the issue body.
//
// nil reader (DATABASE_URL unset at boot) → 503 db_unavailable, matching
// the forecast handler. Real DB errors → 500.
func NewMethodology(r PollsterBiasReader, cfg MethodologyConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "public, max-age=3600")
		if r == nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = w.Write([]byte(dbUnavailableBody))
			return
		}
		priors, err := r.PollsterBiasPriors(req.Context())
		if err != nil {
			slog.Error("methodology_pollsters_read_failed", "err", err)
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(internalErrorBody))
			return
		}
		if priors == nil {
			priors = []PollsterBiasPrior{}
		}
		body := map[string]any{
			"model_version": cfg.ModelVersion,
			"generated_at":  time.Now().UTC().Format(time.RFC3339),
			"presidential": map[string]any{
				"pollster_bias_priors":        priors,
				"fundamentals_features":       cfg.FundamentalsFeatures,
				"sentiment_as_modelled_input": cfg.SentimentAsModelledInput,
				"calibration_thresholds":      cfg.CalibrationThresholds,
			},
			"long_form_url": cfg.LongFormURL,
		}
		w.WriteHeader(http.StatusOK)
		if err := json.NewEncoder(w).Encode(body); err != nil {
			slog.Error("methodology_encode_failed", "err", err)
		}
	}
}
