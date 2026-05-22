package middleware

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// canonicalPayload mirrors the ADR-014 contract — the writer (#33) puts
// run_id, model_version, generated_at and cache_invalid_until at the top
// level. The middleware never parses the body, but the cache_invalid_until
// pass-through assertion below proves that all top-level fields survive
// byte-for-byte regardless.
const canonicalPayload = `{"run_id":"abc","model_version":"0.1.0","generated_at":"2027-06-01T12:00:00-06:00","cache_invalid_until":"2027-06-25T18:00:00-06:00","race":{"type":"presidential"},"candidates":[]}`

func newOKHandler(body []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
	}
}

func expectedETag(body []byte) string {
	sum := sha256.Sum256(body)
	return `"` + hex.EncodeToString(sum[:])[:etagHexLen] + `"`
}

func TestForecastCache_AddsETagOnSuccess(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	if got, want := rec.Header().Get("ETag"), expectedETag([]byte(canonicalPayload)); got != want {
		t.Fatalf("ETag: got %q want %q", got, want)
	}
	if !bytes.Equal(rec.Body.Bytes(), []byte(canonicalPayload)) {
		t.Fatalf("body: got %q want %q", rec.Body.String(), canonicalPayload)
	}
}

func TestForecastCache_ETagIsSHA256First16HexChars(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	body := []byte(`{"hello":"world"}`)
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler(body)).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	tag := rec.Header().Get("ETag")
	unquoted := strings.Trim(tag, `"`)
	if len(unquoted) != etagHexLen {
		t.Fatalf("ETag hex length: got %d want %d (tag=%q)", len(unquoted), etagHexLen, tag)
	}
	sum := sha256.Sum256(body)
	if want := hex.EncodeToString(sum[:])[:etagHexLen]; unquoted != want {
		t.Fatalf("ETag hex: got %q want %q", unquoted, want)
	}
}

func TestForecastCache_ETagDeterministic(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	one := httptest.NewRecorder()
	two := httptest.NewRecorder()
	h := ForecastCache(newOKHandler([]byte(canonicalPayload)))
	h.ServeHTTP(one, httptest.NewRequest(http.MethodGet, "/x", nil))
	h.ServeHTTP(two, httptest.NewRequest(http.MethodGet, "/x", nil))

	if a, b := one.Header().Get("ETag"), two.Header().Get("ETag"); a != b {
		t.Fatalf("ETag not deterministic: %q vs %q", a, b)
	}
}

func TestForecastCache_ETagChangesWhenPayloadChanges(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	a := httptest.NewRecorder()
	b := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(`{"a":1}`))).ServeHTTP(a, httptest.NewRequest(http.MethodGet, "/x", nil))
	ForecastCache(newOKHandler([]byte(`{"a":2}`))).ServeHTTP(b, httptest.NewRequest(http.MethodGet, "/x", nil))

	if a.Header().Get("ETag") == b.Header().Get("ETag") {
		t.Fatalf("ETag must change with payload, both got %q", a.Header().Get("ETag"))
	}
}

func TestForecastCache_CacheControlDefault(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	if got, want := rec.Header().Get("Cache-Control"), "public, max-age=300"; got != want {
		t.Fatalf("Cache-Control: got %q want %q", got, want)
	}
}

func TestForecastCache_CacheControlElectionWeek(t *testing.T) {
	// No t.Parallel(): t.Setenv mutates process-wide state.
	tests := []struct {
		envValue string
		want     string
	}{
		{"true", "public, max-age=60"},
		{"TRUE", "public, max-age=60"},
		{"1", "public, max-age=60"},
		{"t", "public, max-age=60"},
		{"false", "public, max-age=300"},
		{"", "public, max-age=300"},
		{"maybe", "public, max-age=300"}, // garbage → default (fail-open)
	}
	for _, tt := range tests {
		t.Run("env="+tt.envValue, func(t *testing.T) {
			t.Setenv(electionWeekEnvVar, tt.envValue)
			rec := httptest.NewRecorder()
			ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))
			if got := rec.Header().Get("Cache-Control"); got != tt.want {
				t.Fatalf("Cache-Control: got %q want %q", got, tt.want)
			}
		})
	}
}

func TestForecastCache_ContentTypeDefaultedWhenHandlerOmits(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	bare := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"x":1}`))
	})
	rec := httptest.NewRecorder()
	ForecastCache(bare).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	if got := rec.Header().Get("Content-Type"); got != contentTypeJSON {
		t.Fatalf("Content-Type: got %q want %q", got, contentTypeJSON)
	}
}

func TestForecastCache_ContentTypePreservedWhenHandlerSets(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	custom := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"x":1}`))
	})
	rec := httptest.NewRecorder()
	ForecastCache(custom).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	if got := rec.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("Content-Type: got %q want %q", got, "application/json")
	}
}

func TestForecastCache_IfNoneMatch_Returns304NoBody(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	tag := expectedETag([]byte(canonicalPayload))
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("If-None-Match", tag)
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusNotModified; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	if rec.Body.Len() != 0 {
		t.Fatalf("304 must have empty body, got %q", rec.Body.String())
	}
	if got := rec.Header().Get("ETag"); got != tag {
		t.Fatalf("304 must echo ETag: got %q want %q", got, tag)
	}
	if got := rec.Header().Get("Cache-Control"); got != "public, max-age=300" {
		t.Fatalf("304 must include Cache-Control: got %q", got)
	}
}

func TestForecastCache_IfNoneMatchDifferentTag_Returns200(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("If-None-Match", `"deadbeefcafebabe"`)
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusOK; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	if !bytes.Equal(rec.Body.Bytes(), []byte(canonicalPayload)) {
		t.Fatalf("body: got %q", rec.Body.String())
	}
}

func TestForecastCache_IfNoneMatchWildcard_Returns304(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("If-None-Match", "*")
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusNotModified; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
}

func TestForecastCache_IfNoneMatchList_Returns304(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	tag := expectedETag([]byte(canonicalPayload))
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("If-None-Match", `"deadbeefcafebabe", `+tag+`, "feedfacefeedface"`)
	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, req)

	if got, want := rec.Code, http.StatusNotModified; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
}

// TestForecastCache_PassesThroughCacheInvalidUntil pins the most important
// payload-shape contract: the middleware never inspects or mutates the
// payload. cache_invalid_until is the Android client's force-expiry signal
// (#43) — it must reach the wire byte-for-byte.
func TestForecastCache_PassesThroughCacheInvalidUntil(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	rec := httptest.NewRecorder()
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	if !bytes.Equal(rec.Body.Bytes(), []byte(canonicalPayload)) {
		t.Fatalf("body must be byte-for-byte equal:\n got %q\nwant %q", rec.Body.String(), canonicalPayload)
	}
	if !bytes.Contains(rec.Body.Bytes(), []byte(`"cache_invalid_until":"2027-06-25T18:00:00-06:00"`)) {
		t.Fatalf("cache_invalid_until missing from passthrough body: %q", rec.Body.String())
	}
}

// TestForecastCache_NotFoundPassThroughWithoutCacheHeaders asserts that error
// envelopes (404 no_forecast_available, 500 internal, 503 db_unavailable) are
// not decorated — those are never cached at the edge.
func TestForecastCache_NotFoundPassThroughWithoutCacheHeaders(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	notFound := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"error":"no_forecast_available"}`))
	})
	rec := httptest.NewRecorder()
	ForecastCache(notFound).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))

	if got, want := rec.Code, http.StatusNotFound; got != want {
		t.Fatalf("status: got %d want %d", got, want)
	}
	if got := rec.Header().Get("ETag"); got != "" {
		t.Fatalf("error response must not carry ETag: got %q", got)
	}
	if got := rec.Header().Get("Cache-Control"); got != "" {
		t.Fatalf("error response must not carry Cache-Control: got %q", got)
	}
	if got, want := rec.Body.String(), `{"error":"no_forecast_available"}`; got != want {
		t.Fatalf("body: got %q want %q", got, want)
	}
}

// TestForecastCache_BlackoutPrecedence mirrors the production wiring exactly
// so the per-layer ordering documented in ADR-003/ADR-014 is locked in:
// blackout middleware short-circuits before this middleware ever runs, so
// no 503 blackout response gets ETag/Cache-Control decoration.
func TestForecastCache_BlackoutPrecedence(t *testing.T) {
	// No t.Parallel(): t.Setenv mutates process-wide state.
	forecastMux := http.NewServeMux()
	forecastMux.HandleFunc("GET /v1/forecast/presidential", newOKHandler([]byte(canonicalPayload)))
	root := http.NewServeMux()
	root.Handle("/v1/forecast/", Blackout(ForecastCache(forecastMux)))

	t.Run("blackout_off_decorates", func(t *testing.T) {
		t.Setenv("BLACKOUT_ENABLED", "false")
		t.Setenv(electionWeekEnvVar, "")
		req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
		rec := httptest.NewRecorder()
		root.ServeHTTP(rec, req)
		if got, want := rec.Code, http.StatusOK; got != want {
			t.Fatalf("status: got %d want %d", got, want)
		}
		if rec.Header().Get("ETag") == "" {
			t.Fatalf("ETag must be set on 200 forecast response")
		}
	})

	t.Run("blackout_on_skips_decoration", func(t *testing.T) {
		t.Setenv("BLACKOUT_ENABLED", "true")
		t.Setenv(electionWeekEnvVar, "")
		req := httptest.NewRequest(http.MethodGet, "/v1/forecast/presidential", nil)
		rec := httptest.NewRecorder()
		root.ServeHTTP(rec, req)
		if got, want := rec.Code, http.StatusServiceUnavailable; got != want {
			t.Fatalf("status: got %d want %d", got, want)
		}
		if got := rec.Header().Get("ETag"); got != "" {
			t.Fatalf("blackout response must not carry ETag: got %q", got)
		}
		if got := rec.Header().Get("Cache-Control"); got != "" {
			t.Fatalf("blackout response must not carry Cache-Control: got %q", got)
		}
	})
}

// TestForecastCache_IfNoneMatch304SkipsHandlerBody verifies the 304 short
// circuit really truncates the body — important for mobile bandwidth.
func TestForecastCache_IfNoneMatch304BodyBytesZero(t *testing.T) {
	t.Setenv(electionWeekEnvVar, "")

	tag := expectedETag([]byte(canonicalPayload))
	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	req.Header.Set("If-None-Match", tag)

	w := &countingWriter{ResponseWriter: httptest.NewRecorder()}
	ForecastCache(newOKHandler([]byte(canonicalPayload))).ServeHTTP(w, req)

	if w.bodyBytes != 0 {
		t.Fatalf("304 must write zero body bytes to wire, got %d", w.bodyBytes)
	}
}

type countingWriter struct {
	http.ResponseWriter
	bodyBytes int
}

func (c *countingWriter) Write(p []byte) (int, error) {
	c.bodyBytes += len(p)
	return c.ResponseWriter.Write(p)
}
