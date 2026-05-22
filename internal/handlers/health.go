// Package handlers contains the HTTP handlers for the polityk API.
package handlers

import (
	"encoding/json"
	"log/slog"
	"net/http"
)

// Health returns a static {"status":"ok"} payload.
//
// Issue #14 will extend this with DB connectivity, last-published-forecast
// timestamp, and per-source scrape staleness. For now (issue #1) the handler
// stays static so the API can start without a database.
func Health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if err := json.NewEncoder(w).Encode(map[string]string{"status": "ok"}); err != nil {
		slog.Error("health_encode_failed", "err", err)
	}
}
