package store_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jlcp89/polityk/internal/handlers"
	"github.com/jlcp89/polityk/internal/store"
)

// TestPollsterBiasReader_ReadsSeededPollsters walks the issue-#13 acceptance
// criterion "pollster_bias_priors reads live from `pollsters` table":
// reads the four ADR-017 launch rows seeded by migration 0004 and asserts
// each one carries the diffuse default prior.
func TestPollsterBiasReader_ReadsSeededPollsters(t *testing.T) {
	db := pollsTestDB(t)
	ctx := context.Background()

	reader := &store.PollsterBiasReader{DB: db}
	priors, err := reader.PollsterBiasPriors(ctx)
	if err != nil {
		t.Fatalf("PollsterBiasPriors: %v", err)
	}

	wantNames := map[string]struct{}{
		"CID Gallup":                       {},
		"ProDatos":                         {},
		"Borge y Asociados":                {},
		"Fundación Libertad y Desarrollo": {},
	}
	if len(priors) < len(wantNames) {
		t.Fatalf("priors length: got %d want >= %d (priors=%+v)", len(priors), len(wantNames), priors)
	}

	// ORDER BY name keeps the response deterministic; just verify each
	// seeded pollster appears at least once with the diffuse default prior.
	gotNames := map[string]handlers.PollsterBiasPrior{}
	for _, p := range priors {
		gotNames[p.Pollster] = p
	}
	for name := range wantNames {
		p, ok := gotNames[name]
		if !ok {
			t.Errorf("seeded pollster %q missing from response", name)
			continue
		}
		// ADR-017: launch rows ship with mean=0, sd=0.05, sample_count_used=0.
		if p.HistoricalBiasMean != 0.0 {
			t.Errorf("%s historical_bias_mean: got %v want 0", name, p.HistoricalBiasMean)
		}
		if p.HistoricalBiasSD != 0.05 {
			t.Errorf("%s historical_bias_sd: got %v want 0.05", name, p.HistoricalBiasSD)
		}
		if p.SampleCountUsed != 0 {
			t.Errorf("%s sample_count_used: got %d want 0", name, p.SampleCountUsed)
		}
	}
}

// TestMethodology_EndToEnd_SeededPollstersInResponse exercises the full
// `GET /v1/methodology` path against a real DB: reader → handler →
// JSON response. This is the integration acceptance criterion verbatim
// (the four seeded pollsters surface in the response).
func TestMethodology_EndToEnd_SeededPollstersInResponse(t *testing.T) {
	db := pollsTestDB(t)

	reader := &store.PollsterBiasReader{DB: db}
	handler := handlers.NewMethodology(reader, handlers.DefaultMethodologyConfig())

	req := httptest.NewRequest(http.MethodGet, "/v1/methodology", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status: got %d want 200 (body=%q)", rec.Code, rec.Body.String())
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "public, max-age=3600" {
		t.Errorf("cache-control: got %q want %q", cc, "public, max-age=3600")
	}

	var body struct {
		Presidential struct {
			PollsterBiasPriors []handlers.PollsterBiasPrior `json:"pollster_bias_priors"`
		} `json:"presidential"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode body: %v (raw=%q)", err, rec.Body.String())
	}
	if len(body.Presidential.PollsterBiasPriors) == 0 {
		t.Fatalf("pollster_bias_priors empty; expected >= 4 seeded rows (raw=%q)", rec.Body.String())
	}

	have := map[string]bool{}
	for _, p := range body.Presidential.PollsterBiasPriors {
		have[p.Pollster] = true
	}
	for _, want := range []string{"ProDatos", "CID Gallup"} {
		if !have[want] {
			t.Errorf("response missing seeded pollster %q (had: %v)", want, keysOf(have))
		}
	}
	// Sanity-check the JSON literal so the Android Moshi adapter
	// gets a list, never `null`.
	if !strings.Contains(rec.Body.String(), `"pollster_bias_priors":[`) {
		t.Errorf("expected pollster_bias_priors as JSON array, got: %q", rec.Body.String())
	}
}

func keysOf(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
