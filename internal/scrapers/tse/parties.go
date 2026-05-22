// Package tse contains scrapers for the Tribunal Supremo Electoral
// (tse.org.gt) per ADR-004's Go-for-HTML split. The party-list scraper
// fetches the TSE party-registry page, parses active + cancelled parties,
// and UPSERTs them into `parties` + `party_aliases` per ADR-009. Every
// run stamps a row in `scrape_runs` (success or failure) so /v1/health
// (#14) can report ingest staleness.
//
// TSE returns 403 to bare Go clients (no User-Agent) per CLAUDE.md's
// "Critical Domain Rules"; this scraper always sends a current Chrome
// UA and applies exponential backoff with ±20% jitter on 5xx and 403.
package tse

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net/http"
	"regexp"
	"strings"
	"time"
)

// SourcePartyList is the scrape_runs.source identifier for this scraper.
const SourcePartyList = "tse_party_list"

// DefaultUserAgent is a real Chrome UA string. TSE 403s anything without
// a browser-shaped UA (verified empirically; see CLAUDE.md domain rules).
const DefaultUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
	"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"

const (
	defaultPartyListURL = "https://www.tse.org.gt/index.php/partidos-politicos"
	defaultMaxAttempts  = 5
	defaultBackoffBase  = 1 * time.Second
	defaultMaxBackoff   = 30 * time.Second
	defaultHTTPTimeout  = 30 * time.Second
)

// PartyStatus mirrors the party_status ENUM defined in migration 0002.
type PartyStatus string

const (
	StatusActive               PartyStatus = "active"
	StatusCancelled            PartyStatus = "cancelled"
	StatusCancelledUnderAppeal PartyStatus = "cancelled_under_appeal"
)

// ParsedParty is one party as extracted from the TSE registry page.
type ParsedParty struct {
	Name    string
	TSECode string
	Status  PartyStatus
	Aliases []string
}

// Client configures the party-list scrape. NewDefaultClient builds the
// production client; tests inject a shorter BackoffBase and a fixture URL.
type Client struct {
	HTTPClient  *http.Client
	UserAgent   string
	URL         string
	MaxAttempts int
	BackoffBase time.Duration
	MaxBackoff  time.Duration
}

// NewDefaultClient returns the production scrape client targeting the
// live TSE party-registry URL.
func NewDefaultClient() *Client {
	return &Client{
		HTTPClient:  &http.Client{Timeout: defaultHTTPTimeout},
		UserAgent:   DefaultUserAgent,
		URL:         defaultPartyListURL,
		MaxAttempts: defaultMaxAttempts,
		BackoffBase: defaultBackoffBase,
		MaxBackoff:  defaultMaxBackoff,
	}
}

// Run is the single-call entry point matching the issue contract:
//
//	Run(ctx context.Context, db *sql.DB) error
//
// It uses the default production client. For tests with a fixture URL
// or accelerated backoff, build a *Client and call its Run method.
func Run(ctx context.Context, db *sql.DB) error {
	return NewDefaultClient().Run(ctx, db)
}

// Run fetches the configured URL, parses parties, UPSERTs them into the
// schema and stamps `scrape_runs` on success and failure. The scrape_runs
// row is written even when fetch/parse/upsert fails so monitoring can see
// the failed attempt.
func (c *Client) Run(ctx context.Context, db *sql.DB) error {
	body, err := c.fetch(ctx)
	if err != nil {
		_ = stampScrapeRun(ctx, db, SourcePartyList, false, err.Error())
		return fmt.Errorf("fetch: %w", err)
	}
	parsed, err := parseParties(bytes.NewReader(body))
	if err != nil {
		_ = stampScrapeRun(ctx, db, SourcePartyList, false, err.Error())
		return fmt.Errorf("parse: %w", err)
	}
	if err := upsertParties(ctx, db, parsed); err != nil {
		_ = stampScrapeRun(ctx, db, SourcePartyList, false, err.Error())
		return fmt.Errorf("upsert: %w", err)
	}
	if err := stampScrapeRun(ctx, db, SourcePartyList, true, ""); err != nil {
		return fmt.Errorf("stamp scrape_runs: %w", err)
	}
	return nil
}

var errRetriableTransport = errors.New("retriable transport error")

// fetch retries up to MaxAttempts on retriable failures (5xx or 403, or a
// connection-level transport error). Non-retriable 4xx fails fast.
func (c *Client) fetch(ctx context.Context) ([]byte, error) {
	var lastErr error
	for attempt := 0; attempt < c.MaxAttempts; attempt++ {
		if attempt > 0 {
			if err := sleepCtx(ctx, c.backoff(attempt-1)); err != nil {
				return nil, err
			}
		}
		body, status, err := c.doOnce(ctx)
		if err == nil && status >= 200 && status < 300 {
			return body, nil
		}
		if err != nil && !errors.Is(err, errRetriableTransport) {
			return nil, err
		}
		if err != nil {
			lastErr = err
			continue
		}
		if isRetriableStatus(status) {
			lastErr = fmt.Errorf("http status %d", status)
			continue
		}
		return nil, fmt.Errorf("http status %d (non-retriable)", status)
	}
	return nil, fmt.Errorf("exhausted %d attempts: %w", c.MaxAttempts, lastErr)
}

func (c *Client) doOnce(ctx context.Context) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.URL, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml")
	req.Header.Set("Accept-Language", "es-GT,es;q=0.9")
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("%w: %v", errRetriableTransport, err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, fmt.Errorf("read body: %w", err)
	}
	return body, resp.StatusCode, nil
}

func isRetriableStatus(status int) bool {
	return status == http.StatusForbidden || status >= 500
}

// backoff returns the sleep duration for the n-th retry (n=0 → first retry).
// Doubles from BackoffBase, caps at MaxBackoff, applies ±20% jitter.
func (c *Client) backoff(n int) time.Duration {
	base := c.BackoffBase << n
	if base <= 0 {
		base = c.BackoffBase
	}
	if base > c.MaxBackoff {
		base = c.MaxBackoff
	}
	delta := int64(base) / 5
	if delta <= 0 {
		return base
	}
	jitter := rand.Int64N(2*delta+1) - delta
	return base + time.Duration(jitter)
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	if d <= 0 {
		return nil
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

var (
	partyRowRe  = regexp.MustCompile(`(?is)<tr\s+class="party-row"[^>]*?data-tse-code="([^"]+)"[^>]*?data-status="([^"]+)"[^>]*?>(.*?)</tr>`)
	nameCellRe  = regexp.MustCompile(`(?is)<td\s+class="name">(.*?)</td>`)
	aliasCellRe = regexp.MustCompile(`(?is)<td\s+class="aliases">(.*?)</td>`)
)

// parseParties extracts ParsedParty rows from the TSE party-registry HTML.
// Returns an error if no rows are found (page format drift) or any row has
// an unknown status (schema drift); both are loud failures that prevent
// silent under-loading.
func parseParties(r io.Reader) ([]ParsedParty, error) {
	body, err := io.ReadAll(r)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	matches := partyRowRe.FindAllSubmatch(body, -1)
	if len(matches) == 0 {
		return nil, errors.New("no party rows found (page format drift?)")
	}
	parties := make([]ParsedParty, 0, len(matches))
	for _, m := range matches {
		code := strings.TrimSpace(string(m[1]))
		status := PartyStatus(strings.TrimSpace(string(m[2])))
		rowBody := m[3]

		if !isValidStatus(status) {
			return nil, fmt.Errorf("party %s: unknown status %q", code, status)
		}
		nameMatch := nameCellRe.FindSubmatch(rowBody)
		if nameMatch == nil {
			return nil, fmt.Errorf("party %s: missing <td class=\"name\">", code)
		}
		name := strings.TrimSpace(string(nameMatch[1]))
		if name == "" {
			return nil, fmt.Errorf("party %s: empty name", code)
		}

		var aliases []string
		if am := aliasCellRe.FindSubmatch(rowBody); am != nil {
			for _, raw := range strings.Split(string(am[1]), ";") {
				a := strings.TrimSpace(raw)
				if a != "" {
					aliases = append(aliases, a)
				}
			}
		}

		parties = append(parties, ParsedParty{
			Name:    name,
			TSECode: code,
			Status:  status,
			Aliases: aliases,
		})
	}
	return parties, nil
}

func isValidStatus(s PartyStatus) bool {
	switch s {
	case StatusActive, StatusCancelled, StatusCancelledUnderAppeal:
		return true
	}
	return false
}

// upsertParties writes parties + party_aliases idempotently in a single tx.
//
// `parties` is keyed on the unique `tse_code` so re-runs update the same row
// instead of inserting duplicates. `party_aliases (party_id, alias_name)` is
// also UPSERT (ON CONFLICT DO NOTHING) so re-runs don't grow the alias list.
//
// `cancelled_at` is set to now() on the active→cancelled* transition, kept
// otherwise; cleared when status flips back to active. This matches ADR-009:
// "Cancellation is metadata on the same row."
func upsertParties(ctx context.Context, db *sql.DB, parties []ParsedParty) error {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	const upsertPartySQL = `
        INSERT INTO parties (name, tse_code, status, cancelled_at)
        VALUES ($1, $2, $3::party_status,
                CASE WHEN $3 <> 'active' THEN now() ELSE NULL END)
        ON CONFLICT (tse_code) DO UPDATE
        SET name = EXCLUDED.name,
            status = EXCLUDED.status,
            cancelled_at = CASE
                WHEN EXCLUDED.status = 'active' THEN NULL
                WHEN parties.status = 'active' THEN now()
                ELSE parties.cancelled_at
            END
        RETURNING party_id
    `

	const upsertAliasSQL = `
        INSERT INTO party_aliases (party_id, alias_name)
        VALUES ($1, $2)
        ON CONFLICT (party_id, alias_name) DO NOTHING
    `

	for _, p := range parties {
		var partyID int64
		if err := tx.QueryRowContext(ctx, upsertPartySQL, p.Name, p.TSECode, string(p.Status)).Scan(&partyID); err != nil {
			return fmt.Errorf("upsert party %s: %w", p.TSECode, err)
		}
		for _, alias := range p.Aliases {
			if _, err := tx.ExecContext(ctx, upsertAliasSQL, partyID, alias); err != nil {
				return fmt.Errorf("upsert alias %q for party %s: %w", alias, p.TSECode, err)
			}
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit: %w", err)
	}
	return nil
}

// stampScrapeRun UPSERTs the scrape_runs row for `source`. Callers pass
// success=true on the happy path; on failure they pass success=false and
// the wrapped error string. A nil DB is a no-op (the production scraper
// always has one; tests for the parser don't).
func stampScrapeRun(ctx context.Context, db *sql.DB, source string, success bool, errMsg string) error {
	if db == nil {
		return nil
	}
	const stmt = `
        INSERT INTO scrape_runs (source, last_run_at, success, error_message)
        VALUES ($1, now(), $2, NULLIF($3, ''))
        ON CONFLICT (source) DO UPDATE
        SET last_run_at = excluded.last_run_at,
            success = excluded.success,
            error_message = excluded.error_message
    `
	if _, err := db.ExecContext(ctx, stmt, source, success, errMsg); err != nil {
		return fmt.Errorf("stamp scrape_runs: %w", err)
	}
	return nil
}
