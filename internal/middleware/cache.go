package middleware

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
)

// electionWeekEnvVar is the per-request flag that tightens edge caching during
// the week of each electoral vote. Read fresh per request — same contract as
// BLACKOUT_ENABLED — so a config flip or systemd-timer override takes effect
// on the very next response. ADR-014 sets the 60 s upper bound for that week.
const electionWeekEnvVar = "ELECTION_WEEK"

const (
	// etagHexLen is the truncated SHA256 hex prefix length agreed in the
	// issue body (#11). 16 hex chars = 64 bits of entropy — collision
	// probability across the lifetime of the cache is negligible while
	// keeping the ETag short for mobile traffic.
	etagHexLen = 16

	cacheControlDefault      = "public, max-age=300"
	cacheControlElectionWeek = "public, max-age=60"

	contentTypeJSON = "application/json; charset=utf-8"
)

// ForecastCache decorates 200 OK responses from the forecast handlers with the
// caching headers documented in ADR-014:
//
//   - ETag: first 16 hex chars of SHA256(body) — stable for identical bytes
//   - Cache-Control: public, max-age=300 (default) or 60 when ELECTION_WEEK=true
//   - Content-Type: application/json; charset=utf-8 (sets the default if the
//     handler did not set one)
//
// On a matching If-None-Match the middleware short-circuits with 304 and an
// empty body — ETag and Cache-Control are still emitted per RFC 7232 §4.1 so
// downstream caches keep the freshness window.
//
// Non-200 responses (404 no_forecast_available, 500 internal, 503 from a nil
// reader) pass through unchanged: ETag-based caching only applies to the
// canonical published payload, never to error envelopes. The blackout 503 is
// already short-circuited by middleware.Blackout above this handler, so this
// middleware is only ever invoked when forecasts are legally servable.
//
// The payload's top-level cache_invalid_until field — when present — is passed
// through byte-for-byte (the middleware never parses or mutates the body); the
// Android client (#43) reads it to force-drop its Room cache at blackout start.
func ForecastCache(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c := newCacheCapture(w)
		next.ServeHTTP(c, r)
		c.finalize(r)
	})
}

// cacheCapture buffers the downstream handler's status + body so the
// middleware can decide on headers (ETag, Cache-Control) and 304 short-circuit
// before anything is committed to the wire. Headers set by the handler land
// directly on the underlying ResponseWriter's header map (Header() returns it
// verbatim), so we only need to buffer the body and status.
type cacheCapture struct {
	underlying  http.ResponseWriter
	body        bytes.Buffer
	status      int
	wroteHeader bool
}

func newCacheCapture(w http.ResponseWriter) *cacheCapture {
	return &cacheCapture{underlying: w, status: http.StatusOK}
}

func (c *cacheCapture) Header() http.Header { return c.underlying.Header() }

func (c *cacheCapture) WriteHeader(status int) {
	if c.wroteHeader {
		return
	}
	c.status = status
	c.wroteHeader = true
}

func (c *cacheCapture) Write(p []byte) (int, error) {
	if !c.wroteHeader {
		c.WriteHeader(http.StatusOK)
	}
	return c.body.Write(p)
}

// finalize commits the captured response to the wire, adding cache headers on
// 200s and short-circuiting to 304 when the client's If-None-Match matches.
func (c *cacheCapture) finalize(r *http.Request) {
	if c.status != http.StatusOK || c.body.Len() == 0 {
		c.passthrough()
		return
	}
	etag := computeETag(c.body.Bytes())
	h := c.underlying.Header()
	h.Set("ETag", etag)
	h.Set("Cache-Control", cacheControlValue())
	if h.Get("Content-Type") == "" {
		h.Set("Content-Type", contentTypeJSON)
	}
	if etagMatches(r.Header.Get("If-None-Match"), etag) {
		c.underlying.WriteHeader(http.StatusNotModified)
		return
	}
	c.underlying.WriteHeader(c.status)
	if _, err := c.underlying.Write(c.body.Bytes()); err != nil {
		slog.Error("forecast_cache_write_failed", "err", err)
	}
}

// passthrough writes a non-OK or empty-body response straight to the underlying
// writer with no ETag/Cache-Control decoration. The handler's headers are
// already on the underlying map so we only replay status + body.
func (c *cacheCapture) passthrough() {
	c.underlying.WriteHeader(c.status)
	if c.body.Len() == 0 {
		return
	}
	if _, err := c.underlying.Write(c.body.Bytes()); err != nil {
		slog.Error("forecast_cache_passthrough_failed", "err", err, "status", c.status)
	}
}

func computeETag(body []byte) string {
	sum := sha256.Sum256(body)
	return `"` + hex.EncodeToString(sum[:])[:etagHexLen] + `"`
}

// etagMatches honours the RFC 7232 §3.2 list form: the client may send several
// comma-separated tags, plus the wildcard `*`. We compare against the server
// tag's strong form only (the writer never emits weak ETags).
func etagMatches(headerValue, serverTag string) bool {
	if headerValue == "" {
		return false
	}
	for _, candidate := range strings.Split(headerValue, ",") {
		candidate = strings.TrimSpace(candidate)
		if candidate == "*" || candidate == serverTag {
			return true
		}
	}
	return false
}

// cacheControlValue returns the public max-age policy ADR-014 mandates: a
// 5-minute default that tightens to 60 s during ELECTION_WEEK. Anything other
// than a strict-bool truthy value (1/t/T/TRUE/true/True) keeps the default —
// mirroring the fail-open semantics of the blackout flag so a typo never
// silently locks the API into the wrong cache window.
func cacheControlValue() string {
	if electionWeekActive() {
		return cacheControlElectionWeek
	}
	return cacheControlDefault
}

func electionWeekActive() bool {
	v, err := strconv.ParseBool(os.Getenv(electionWeekEnvVar))
	if err != nil {
		return false
	}
	return v
}
