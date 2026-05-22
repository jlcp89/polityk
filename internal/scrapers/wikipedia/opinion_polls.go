// Package wikipedia ingests Guatemalan presidential opinion polls from the
// English-language Wikipedia opinion-polling article via the Wikipedia REST
// API (per issue #17, ADR-017). The 2027 article is the production target
// once it exists; until then the 2023 article is the backfill source. Polls
// are matched on (pollster_id, field_end, source_url) and rejected as
// duplicates per polls' UNIQUE constraint (migration 0004).
package wikipedia

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"golang.org/x/net/html"
)

// SourceTag is the canonical scrape_runs.source value for this scraper.
const SourceTag = "wikipedia_polls"

// DefaultBaseURL is the Wikipedia REST API HTML endpoint root. The full
// fetch URL is `<BaseURL>/<percent-encoded title>`.
const DefaultBaseURL = "https://en.wikipedia.org/api/rest_v1/page/html"

// Page2023 is the 2023 Guatemalan-election Wikipedia article (backfill).
const Page2023 = "Opinion_polling_for_the_2023_Guatemalan_general_election"

// Page2027 is the 2027-election Wikipedia article (production target;
// will 404 until the article exists, in which case callers should fall
// back to Page2023).
const Page2027 = "Opinion_polling_for_the_2027_Guatemalan_general_election"

// Scraper hits the Wikipedia REST API, parses the wikitable rows, resolves
// pollster and candidate names against the polityk DB, and upserts into
// polls + poll_responses. A successful or failed run always stamps
// scrape_runs (source=wikipedia_polls).
type Scraper struct {
	// HTTPClient defaults to http.DefaultClient with a 30s timeout when nil.
	HTTPClient *http.Client
	// BaseURL defaults to DefaultBaseURL when empty.
	BaseURL string
	// PageTitle defaults to Page2023 when empty.
	PageTitle string
	// UserAgent identifies the scraper to Wikipedia (their guidelines
	// require a real UA + contact URL).
	UserAgent string
	// Logger receives WARN-level events for unresolved pollster/candidate
	// names; defaults to slog.Default() when nil.
	Logger *slog.Logger
}

// PollRow is the parsed shape of a single wikitable poll row.
type PollRow struct {
	Pollster       string
	FieldStart     time.Time
	FieldEnd       time.Time
	SampleSize     sql.NullInt32
	MarginOfError  sql.NullFloat64
	CandidateShare map[string]float64
}

// RunStats is returned by Run for the integration test + caller.
type RunStats struct {
	PollsInserted          int
	PollsDuplicate         int
	ResponsesInserted      int
	UnresolvedPollsterRows int
	UnresolvedCandidates   int
}

// Run is the scraper's entrypoint. Fetches the Wikipedia HTML, parses the
// poll table, and upserts to the DB. scrape_runs is stamped on every
// invocation (success or failure).
func (s *Scraper) Run(ctx context.Context, db *sql.DB) (RunStats, error) {
	logger := s.logger()
	pageURL, fetchURL := s.urls()

	stats, runErr := s.runOnce(ctx, db, logger, pageURL, fetchURL)
	if stampErr := stampScrapeRun(ctx, db, runErr); stampErr != nil {
		logger.Error("scrape_runs_stamp_failed", "err", stampErr)
		if runErr == nil {
			runErr = fmt.Errorf("stamp scrape_runs: %w", stampErr)
		}
	}
	return stats, runErr
}

func (s *Scraper) runOnce(
	ctx context.Context,
	db *sql.DB,
	logger *slog.Logger,
	pageURL, fetchURL string,
) (RunStats, error) {
	var stats RunStats
	body, err := s.fetch(ctx, fetchURL)
	if err != nil {
		return stats, fmt.Errorf("fetch %s: %w", fetchURL, err)
	}
	defer body.Close()

	rows, err := ParseWikitable(body)
	if err != nil {
		return stats, fmt.Errorf("parse wikitable: %w", err)
	}

	return ingestRows(ctx, db, logger, pageURL, rows)
}

func (s *Scraper) logger() *slog.Logger {
	if s.Logger != nil {
		return s.Logger
	}
	return slog.Default()
}

func (s *Scraper) urls() (pageURL, fetchURL string) {
	base := s.BaseURL
	if base == "" {
		base = DefaultBaseURL
	}
	title := s.PageTitle
	if title == "" {
		title = Page2023
	}
	fetchURL = strings.TrimRight(base, "/") + "/" + url.PathEscape(title)
	pageURL = "https://en.wikipedia.org/wiki/" + url.PathEscape(title)
	return pageURL, fetchURL
}

func (s *Scraper) fetch(ctx context.Context, fetchURL string) (io.ReadCloser, error) {
	client := s.HTTPClient
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, fetchURL, nil)
	if err != nil {
		return nil, err
	}
	ua := s.UserAgent
	if ua == "" {
		ua = "polityk-wikipedia-poll-scraper/0.1 (+https://github.com/jlcp89/polityk)"
	}
	req.Header.Set("User-Agent", ua)
	req.Header.Set("Accept", "text/html")

	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		_ = resp.Body.Close()
		return nil, fmt.Errorf("status %d", resp.StatusCode)
	}
	return resp.Body, nil
}

// ingestRows is exported via Run; pulled into its own function for testability.
func ingestRows(
	ctx context.Context,
	db *sql.DB,
	logger *slog.Logger,
	sourceURL string,
	rows []PollRow,
) (RunStats, error) {
	var stats RunStats
	for _, row := range rows {
		pollsterID, ok, err := resolvePollster(ctx, db, row.Pollster)
		if err != nil {
			return stats, fmt.Errorf("resolve pollster %q: %w", row.Pollster, err)
		}
		if !ok {
			stats.UnresolvedPollsterRows++
			logger.Warn("wikipedia_polls_unresolved_pollster",
				"pollster", row.Pollster,
				"field_end", row.FieldEnd.Format("2006-01-02"),
			)
			continue
		}

		pollID, inserted, err := upsertPoll(ctx, db, pollsterID, row, sourceURL)
		if err != nil {
			return stats, fmt.Errorf("upsert poll for %q: %w", row.Pollster, err)
		}
		if inserted {
			stats.PollsInserted++
		} else {
			stats.PollsDuplicate++
			continue
		}

		for candName, share := range row.CandidateShare {
			candID, ok, err := resolveCandidate(ctx, db, candName)
			if err != nil {
				return stats, fmt.Errorf("resolve candidate %q: %w", candName, err)
			}
			if !ok {
				stats.UnresolvedCandidates++
				logger.Warn("wikipedia_polls_unresolved_candidate",
					"candidate", candName,
					"pollster", row.Pollster,
					"field_end", row.FieldEnd.Format("2006-01-02"),
				)
				continue
			}
			if err := insertResponse(ctx, db, pollID, candID, share, row.MarginOfError); err != nil {
				return stats, fmt.Errorf("insert response %q/%q: %w", row.Pollster, candName, err)
			}
			stats.ResponsesInserted++
		}
	}
	return stats, nil
}

func resolvePollster(ctx context.Context, db *sql.DB, name string) (int64, bool, error) {
	trimmed := strings.TrimSpace(name)
	if trimmed == "" {
		return 0, false, nil
	}
	const q = `
		SELECT pollster_id FROM pollsters
		WHERE LOWER(name) = LOWER($1)
		LIMIT 1
	`
	var id int64
	err := db.QueryRowContext(ctx, q, trimmed).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, err
	}
	return id, true, nil
}

func resolveCandidate(ctx context.Context, db *sql.DB, name string) (int64, bool, error) {
	trimmed := strings.TrimSpace(name)
	if trimmed == "" {
		return 0, false, nil
	}
	const q = `
		SELECT candidate_id FROM candidates WHERE LOWER(full_name) = LOWER($1)
		UNION ALL
		SELECT candidate_id FROM candidate_aliases WHERE LOWER(alias_name) = LOWER($1)
		LIMIT 1
	`
	var id int64
	err := db.QueryRowContext(ctx, q, trimmed).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, err
	}
	return id, true, nil
}

func upsertPoll(
	ctx context.Context,
	db *sql.DB,
	pollsterID int64,
	row PollRow,
	sourceURL string,
) (int64, bool, error) {
	const q = `
		INSERT INTO polls (pollster_id, field_start, field_end, sample_size, methodology, source_url)
		VALUES ($1, $2, $3, $4, $5, $6)
		ON CONFLICT (pollster_id, field_end, source_url) DO NOTHING
		RETURNING poll_id
	`
	var id int64
	err := db.QueryRowContext(ctx, q,
		pollsterID,
		row.FieldStart,
		row.FieldEnd,
		row.SampleSize,
		sql.NullString{}, // methodology — not present in the wikitable
		sourceURL,
	).Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		// Duplicate row; look up the existing poll_id so the caller can
		// log it but skip re-inserting responses.
		const lookup = `
			SELECT poll_id FROM polls
			WHERE pollster_id = $1 AND field_end = $2 AND source_url = $3
			LIMIT 1
		`
		if err := db.QueryRowContext(ctx, lookup, pollsterID, row.FieldEnd, sourceURL).Scan(&id); err != nil {
			return 0, false, err
		}
		return id, false, nil
	}
	if err != nil {
		return 0, false, err
	}
	return id, true, nil
}

func insertResponse(
	ctx context.Context,
	db *sql.DB,
	pollID, candidateID int64,
	share float64,
	moe sql.NullFloat64,
) error {
	const q = `
		INSERT INTO poll_responses (poll_id, candidate_id, share, margin_of_error)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (poll_id, candidate_id) DO NOTHING
	`
	_, err := db.ExecContext(ctx, q, pollID, candidateID, share, moe)
	return err
}

func stampScrapeRun(ctx context.Context, db *sql.DB, runErr error) error {
	const q = `
		INSERT INTO scrape_runs (source, last_run_at, success, error_message)
		VALUES ($1, now(), $2, $3)
		ON CONFLICT (source) DO UPDATE SET
			last_run_at = EXCLUDED.last_run_at,
			success     = EXCLUDED.success,
			error_message = EXCLUDED.error_message
	`
	var msg sql.NullString
	if runErr != nil {
		msg = sql.NullString{String: runErr.Error(), Valid: true}
	}
	_, err := db.ExecContext(ctx, q, SourceTag, runErr == nil, msg)
	return err
}

// ParseWikitable walks the HTML, finds the first `<table class="wikitable">`
// and emits one PollRow per data row. Rows with unparseable dates are
// dropped silently (Wikipedia's "Polls for the runoff" and section-header
// pseudo-rows show up here); the caller's downstream resolution log still
// fires on the rows that survive parsing.
func ParseWikitable(r io.Reader) ([]PollRow, error) {
	doc, err := html.Parse(r)
	if err != nil {
		return nil, err
	}
	table := findWikitable(doc)
	if table == nil {
		return nil, errors.New("no wikitable found")
	}

	headers, dataRows := splitTable(table)
	if len(headers) < 4 {
		return nil, fmt.Errorf("unexpected header count %d (want >=4)", len(headers))
	}
	colIndex := mapHeaderColumns(headers)
	if colIndex.pollster < 0 || colIndex.fieldDate < 0 {
		return nil, errors.New("required columns not found (pollster + fieldwork)")
	}

	var out []PollRow
	for _, cells := range dataRows {
		if len(cells) < len(headers) {
			// Section divider or merged-cell row; skip without erroring.
			continue
		}
		start, end, ok := parseDateRange(cells[colIndex.fieldDate])
		if !ok {
			continue
		}
		row := PollRow{
			Pollster:       strings.TrimSpace(cells[colIndex.pollster]),
			FieldStart:     start,
			FieldEnd:       end,
			SampleSize:     parseSampleSize(cellOrEmpty(cells, colIndex.sampleSize)),
			MarginOfError:  parseMOE(cellOrEmpty(cells, colIndex.marginOfError)),
			CandidateShare: map[string]float64{},
		}
		for _, c := range colIndex.candidates {
			if c.col >= len(cells) {
				continue
			}
			share, ok := parsePercent(cells[c.col])
			if !ok {
				continue
			}
			row.CandidateShare[c.name] = share
		}
		if len(row.CandidateShare) == 0 {
			continue
		}
		out = append(out, row)
	}
	return out, nil
}

type columnIndex struct {
	pollster, fieldDate, sampleSize, marginOfError int
	candidates                                     []candidateColumn
}

type candidateColumn struct {
	name string
	col  int
}

func mapHeaderColumns(headers []string) columnIndex {
	idx := columnIndex{pollster: -1, fieldDate: -1, sampleSize: -1, marginOfError: -1}
	for i, h := range headers {
		norm := strings.ToLower(strings.TrimSpace(h))
		switch {
		case idx.pollster < 0 && (strings.Contains(norm, "polling firm") || strings.Contains(norm, "pollster")):
			idx.pollster = i
		case idx.fieldDate < 0 && (strings.Contains(norm, "fieldwork") || strings.Contains(norm, "date")):
			idx.fieldDate = i
		case idx.sampleSize < 0 && strings.Contains(norm, "sample"):
			idx.sampleSize = i
		case idx.marginOfError < 0 && (strings.Contains(norm, "margin") || strings.Contains(norm, "error")):
			idx.marginOfError = i
		default:
			if isCandidateHeader(h) {
				idx.candidates = append(idx.candidates, candidateColumn{
					name: strings.TrimSpace(h),
					col:  i,
				})
			}
		}
	}
	return idx
}

// isCandidateHeader treats any non-empty header that doesn't look like a
// known metadata column as a candidate column. Wikipedia tables also
// include columns like "Lead" (margin between top two) which we skip.
func isCandidateHeader(h string) bool {
	norm := strings.ToLower(strings.TrimSpace(h))
	if norm == "" {
		return false
	}
	skip := []string{
		"polling firm", "pollster", "fieldwork", "date",
		"sample", "margin", "error", "lead", "abs", "n/a",
		"undecided", "other", "ns/nc", "no opinion",
	}
	for _, s := range skip {
		if strings.Contains(norm, s) {
			return false
		}
	}
	return true
}

func findWikitable(n *html.Node) *html.Node {
	if n.Type == html.ElementNode && n.Data == "table" {
		for _, a := range n.Attr {
			if a.Key == "class" && strings.Contains(a.Val, "wikitable") {
				return n
			}
		}
	}
	for c := n.FirstChild; c != nil; c = c.NextSibling {
		if r := findWikitable(c); r != nil {
			return r
		}
	}
	return nil
}

func splitTable(table *html.Node) (headers []string, rows [][]string) {
	for _, tr := range trIter(table) {
		cells := cellTextsForRow(tr)
		if len(cells) == 0 {
			continue
		}
		if headers == nil && hasHeaderCell(tr) {
			headers = cells
			continue
		}
		rows = append(rows, cells)
	}
	return headers, rows
}

// trIter yields all <tr> descendants of n in document order. Returns a
// channel-style iterator implemented via a slice for Go 1.22 compatibility.
func trIter(n *html.Node) []*html.Node {
	var out []*html.Node
	var walk func(*html.Node)
	walk = func(node *html.Node) {
		if node.Type == html.ElementNode && node.Data == "tr" {
			out = append(out, node)
		}
		for c := node.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(n)
	return out
}

func hasHeaderCell(tr *html.Node) bool {
	for c := tr.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode && c.Data == "th" {
			return true
		}
	}
	return false
}

func cellTextsForRow(tr *html.Node) []string {
	var out []string
	for c := tr.FirstChild; c != nil; c = c.NextSibling {
		if c.Type != html.ElementNode {
			continue
		}
		if c.Data == "th" || c.Data == "td" {
			out = append(out, strings.TrimSpace(extractText(c)))
		}
	}
	return out
}

func extractText(n *html.Node) string {
	var sb strings.Builder
	var walk func(*html.Node)
	walk = func(node *html.Node) {
		if node.Type == html.TextNode {
			sb.WriteString(node.Data)
		}
		// Skip footnote sup tags so "1,200[1]" becomes "1,200".
		if node.Type == html.ElementNode && node.Data == "sup" {
			return
		}
		for c := node.FirstChild; c != nil; c = c.NextSibling {
			walk(c)
		}
	}
	walk(n)
	return collapseWhitespace(sb.String())
}

var whitespaceRE = regexp.MustCompile(`[\s\xc2\xa0]+`)

func collapseWhitespace(s string) string {
	return strings.TrimSpace(whitespaceRE.ReplaceAllString(s, " "))
}

func cellOrEmpty(cells []string, idx int) string {
	if idx < 0 || idx >= len(cells) {
		return ""
	}
	return cells[idx]
}

// parseDateRange accepts forms like "1–10 May 2023", "1-10 May 2023",
// "5–15 June 2023", "30 April – 2 May 2023", "12 June 2023" (single day),
// returning (start, end, ok). Whitespace and en/em dashes are normalised.
func parseDateRange(s string) (time.Time, time.Time, bool) {
	clean := collapseWhitespace(s)
	clean = strings.ReplaceAll(clean, "–", "-")
	clean = strings.ReplaceAll(clean, "—", "-")

	// Cross-month range "30 April - 2 May 2023".
	if t1, t2, ok := tryCrossMonthRange(clean); ok {
		return t1, t2, true
	}

	// Same-month range "1-10 May 2023".
	if t1, t2, ok := trySameMonthRange(clean); ok {
		return t1, t2, true
	}

	// Single-day "12 June 2023".
	if t, ok := tryParseDate(clean); ok {
		return t, t, true
	}
	return time.Time{}, time.Time{}, false
}

var sameMonthRangeRE = regexp.MustCompile(`^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$`)
var crossMonthRangeRE = regexp.MustCompile(`^(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$`)

func trySameMonthRange(s string) (time.Time, time.Time, bool) {
	m := sameMonthRangeRE.FindStringSubmatch(s)
	if m == nil {
		return time.Time{}, time.Time{}, false
	}
	start, ok1 := tryParseDate(m[1] + " " + m[3] + " " + m[4])
	end, ok2 := tryParseDate(m[2] + " " + m[3] + " " + m[4])
	if !ok1 || !ok2 {
		return time.Time{}, time.Time{}, false
	}
	return start, end, true
}

func tryCrossMonthRange(s string) (time.Time, time.Time, bool) {
	m := crossMonthRangeRE.FindStringSubmatch(s)
	if m == nil {
		return time.Time{}, time.Time{}, false
	}
	year := m[5]
	start, ok1 := tryParseDate(m[1] + " " + m[2] + " " + year)
	end, ok2 := tryParseDate(m[3] + " " + m[4] + " " + year)
	if !ok1 || !ok2 {
		return time.Time{}, time.Time{}, false
	}
	return start, end, true
}

func tryParseDate(s string) (time.Time, bool) {
	for _, layout := range []string{"2 January 2006", "2 Jan 2006"} {
		if t, err := time.Parse(layout, strings.TrimSpace(s)); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func parseSampleSize(s string) sql.NullInt32 {
	clean := strings.ReplaceAll(collapseWhitespace(s), ",", "")
	if clean == "" {
		return sql.NullInt32{}
	}
	n, err := strconv.Atoi(clean)
	if err != nil || n <= 0 {
		return sql.NullInt32{}
	}
	return sql.NullInt32{Int32: int32(n), Valid: true}
}

var percentRE = regexp.MustCompile(`([0-9]+(?:\.[0-9]+)?)\s*%?`)

func parsePercent(s string) (float64, bool) {
	clean := collapseWhitespace(s)
	if clean == "" || strings.EqualFold(clean, "-") || strings.EqualFold(clean, "n/a") {
		return 0, false
	}
	m := percentRE.FindStringSubmatch(clean)
	if m == nil {
		return 0, false
	}
	n, err := strconv.ParseFloat(m[1], 64)
	if err != nil {
		return 0, false
	}
	if n < 0 || n > 100 {
		return 0, false
	}
	return n / 100.0, true
}

func parseMOE(s string) sql.NullFloat64 {
	if v, ok := parsePercent(s); ok {
		return sql.NullFloat64{Float64: v, Valid: true}
	}
	return sql.NullFloat64{}
}
