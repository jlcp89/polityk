package rss

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/mmcdole/gofeed"
)

// SourceRSSArchive is the scrape_runs.source identifier for archive-mode
// runs. Distinct from the live-RSS run so /v1/health can report each.
const SourceRSSArchive = "rss_archive"

// CDXBaseURL is the Internet Archive CDX search endpoint. CDX returns a
// JSON array of [timestamp, original_url] tuples for every Wayback
// snapshot of the given URL in the requested date range.
const CDXBaseURL = "https://web.archive.org/cdx/search/cdx"

// WaybackRawBase is the prefix for an archived asset fetched without
// Wayback's HTML/banner wrapper. Append "<timestamp>id_/<original_url>".
const WaybackRawBase = "https://web.archive.org/web/"

// defaultArchiveDelay rate-limits requests to Wayback Machine. The IA
// asks API users to stay under ~5 req/s and to back off on 429s; 1.5s
// is a conservative single-thread cadence that also leaves headroom
// for the per-snapshot RSS body fetch.
const defaultArchiveDelay = 1500 * time.Millisecond

// ArchiveOutlet describes one historical feed URL to backfill.
type ArchiveOutlet struct {
	// Name is the outlet display + scrape_runs identifier — must match
	// the live outlet (see Sources()) so URL-based dedup works when both
	// live and archive runs ingest the same article.
	Name string
	// FeedURL is the publisher's RSS URL at the time the snapshots were
	// taken. Use the historical URL, not the current one, when probing
	// CDX — Wayback indexes by literal URL.
	FeedURL string
}

// ArchiveWindow defines an inclusive date range to sample from.
type ArchiveWindow struct {
	From    time.Time
	To      time.Time
	Samples int // approx number of snapshots to fetch per outlet
}

// DefaultArchiveOutlets are the same outlets as Sources() but keyed to
// their historical RSS URLs as of 2019/2023. Some current URLs return
// 404 (Plaza Pública's /rss.xml, Publinews, Soy502); the archive flow
// still works against the historical URLs because Wayback indexes the
// content that was published at those URLs at the time.
func DefaultArchiveOutlets() []ArchiveOutlet {
	return []ArchiveOutlet{
		{Name: "Prensa Libre", FeedURL: "https://www.prensalibre.com/feed/"},
		{Name: "Prensa Libre", FeedURL: "https://www.prensalibre.com/guatemala/politica/feed/"},
		{Name: "La Hora", FeedURL: "https://lahora.gt/feed/"},
		{Name: "Soy502", FeedURL: "https://www.soy502.com/rss.xml"},
		{Name: "Plaza Pública", FeedURL: "https://www.plazapublica.com.gt/rss.xml"},
		{Name: "Publinews", FeedURL: "https://www.publinews.gt/rss/"},
		{Name: "Emisoras Unidas", FeedURL: "https://emisorasunidas.com/feed/"},
		{Name: "República", FeedURL: "https://republica.gt/feed/"},
		{Name: "Guatemala.com", FeedURL: "https://aprende.guatemala.com/feed/"},
	}
}

// DefaultArchiveWindows are the two Guatemalan general-election
// campaign periods. Sampling these brings the corpus into the
// time-frame where 2027-prospective candidates were active and
// headlines mention them by name.
func DefaultArchiveWindows() []ArchiveWindow {
	return []ArchiveWindow{
		{
			From:    time.Date(2019, 4, 1, 0, 0, 0, 0, time.UTC),
			To:      time.Date(2019, 9, 30, 23, 59, 59, 0, time.UTC),
			Samples: 8,
		},
		{
			From:    time.Date(2023, 3, 1, 0, 0, 0, 0, time.UTC),
			To:      time.Date(2023, 9, 30, 23, 59, 59, 0, time.UTC),
			Samples: 8,
		},
	}
}

// ArchiveClient configures the Wayback Machine integration.
type ArchiveClient struct {
	HTTPClient *http.Client
	UserAgent  string
	Outlets    []ArchiveOutlet
	Windows    []ArchiveWindow
	MinDelay   time.Duration
	Logger     *slog.Logger

	// CDXBase overrides the CDX search endpoint. Defaults to
	// CDXBaseURL when empty. Tests inject a test-server URL.
	CDXBase string
	// WaybackBase overrides the Wayback raw-content base. Defaults to
	// WaybackRawBase when empty. Tests inject a test-server URL.
	WaybackBase string
}

// NewDefaultArchiveClient builds the production archive scraper.
func NewDefaultArchiveClient() *ArchiveClient {
	return &ArchiveClient{
		HTTPClient: &http.Client{Timeout: 30 * time.Second},
		UserAgent:  DefaultUserAgent,
		Outlets:    DefaultArchiveOutlets(),
		Windows:    DefaultArchiveWindows(),
		MinDelay:   defaultArchiveDelay,
		Logger:     slog.Default(),
	}
}

// ArchiveRun fetches Wayback-indexed snapshots of each outlet's
// historical RSS feed across the configured windows and ingests every
// article in those snapshots into news_articles. Existing URLs dedup
// via ON CONFLICT — re-running is idempotent.
func ArchiveRun(ctx context.Context, db *sql.DB) error {
	return NewDefaultArchiveClient().Run(ctx, db)
}

// Run drives the configured ArchiveClient end-to-end and stamps
// scrape_runs on completion.
func (c *ArchiveClient) Run(ctx context.Context, db *sql.DB) error {
	if c.Logger == nil {
		c.Logger = slog.Default()
	}
	var totalInserted int
	var perOutletErrors []string
	for _, outlet := range c.Outlets {
		for _, window := range c.Windows {
			inserted, err := c.runOutletWindow(ctx, db, outlet, window)
			if err != nil {
				c.Logger.Warn("archive outlet window failed",
					slog.String("outlet", outlet.Name),
					slog.String("from", window.From.Format("2006-01-02")),
					slog.String("to", window.To.Format("2006-01-02")),
					slog.String("error", err.Error()))
				perOutletErrors = append(perOutletErrors,
					fmt.Sprintf("%s [%s..%s]: %s",
						outlet.Name,
						window.From.Format("2006-01-02"),
						window.To.Format("2006-01-02"),
						err.Error()))
				continue
			}
			totalInserted += inserted
			c.Logger.Info("archive outlet window ok",
				slog.String("outlet", outlet.Name),
				slog.String("from", window.From.Format("2006-01-02")),
				slog.String("to", window.To.Format("2006-01-02")),
				slog.Int("inserted", inserted))
		}
	}
	errMsg := ""
	if len(perOutletErrors) > 0 {
		errMsg = "partial: " + strings.Join(perOutletErrors, "; ")
	}
	if err := stampScrapeRun(ctx, db, SourceRSSArchive, true, errMsg); err != nil {
		return fmt.Errorf("stamp scrape_runs: %w", err)
	}
	return nil
}

// runOutletWindow queries CDX, samples ~Samples snapshots evenly, and
// for each sampled snapshot fetches the archived RSS, parses items,
// and UPSERTs them into news_articles.
func (c *ArchiveClient) runOutletWindow(
	ctx context.Context,
	db *sql.DB,
	outlet ArchiveOutlet,
	window ArchiveWindow,
) (int, error) {
	stamps, err := c.queryCDX(ctx, outlet.FeedURL, window.From, window.To)
	if err != nil {
		return 0, fmt.Errorf("cdx: %w", err)
	}
	if len(stamps) == 0 {
		return 0, nil
	}
	sampled := evenSample(stamps, window.Samples)
	seenURL := map[string]bool{}
	var inserted int
	for i, ts := range sampled {
		if i > 0 {
			if err := sleepCtx(ctx, c.MinDelay); err != nil {
				return inserted, err
			}
		}
		items, err := c.fetchArchivedFeed(ctx, ts, outlet.FeedURL)
		if err != nil {
			c.Logger.Warn("archive snapshot failed",
				slog.String("outlet", outlet.Name),
				slog.String("timestamp", ts),
				slog.String("error", err.Error()))
			continue
		}
		for _, it := range items {
			if seenURL[it.URL] {
				continue
			}
			seenURL[it.URL] = true
			n, err := insertArticle(ctx, db, outlet.Name, it.URL, it.Title, it.Body, it.PublishedAt)
			if err != nil {
				c.Logger.Warn("archive insert failed",
					slog.String("outlet", outlet.Name),
					slog.String("url", it.URL),
					slog.String("error", err.Error()))
				continue
			}
			inserted += n
		}
	}
	return inserted, nil
}

// archivedItem mirrors fetchedItem but carries an RSS-supplied body
// snippet (description / content:encoded) so we never insert an empty
// body_text. The body is the lede, not the full article — sufficient
// for the headline-validation use case.
type archivedItem struct {
	URL         string
	Title       string
	Body        string
	PublishedAt *time.Time
}

// queryCDX returns the list of Wayback timestamps (YYYYMMDDHHmmss) for
// the given URL in the date range. Filters to statuscode:200.
func (c *ArchiveClient) queryCDX(ctx context.Context, feedURL string, from, to time.Time) ([]string, error) {
	q := url.Values{}
	q.Set("url", feedURL)
	q.Set("from", from.Format("20060102"))
	q.Set("to", to.Format("20060102"))
	q.Set("output", "json")
	q.Set("filter", "statuscode:200")
	q.Set("fl", "timestamp")
	q.Set("limit", "200")
	base := c.CDXBase
	if base == "" {
		base = CDXBaseURL
	}
	endpoint := base + "?" + q.Encode()
	body, err := c.httpGet(ctx, endpoint)
	if err != nil {
		return nil, err
	}
	var rows [][]string
	if err := json.Unmarshal(body, &rows); err != nil {
		return nil, fmt.Errorf("parse cdx json: %w", err)
	}
	if len(rows) < 2 {
		return nil, nil
	}
	// First row is the header; subsequent rows are data.
	out := make([]string, 0, len(rows)-1)
	for _, r := range rows[1:] {
		if len(r) >= 1 && r[0] != "" {
			out = append(out, r[0])
		}
	}
	return out, nil
}

// fetchArchivedFeed retrieves the raw archived RSS payload at the
// given timestamp and parses it into archivedItem records.
func (c *ArchiveClient) fetchArchivedFeed(ctx context.Context, timestamp, feedURL string) ([]archivedItem, error) {
	base := c.WaybackBase
	if base == "" {
		base = WaybackRawBase
	}
	raw := base + timestamp + "id_/" + feedURL
	body, err := c.httpGet(ctx, raw)
	if err != nil {
		return nil, err
	}
	parser := gofeed.NewParser()
	feed, err := parser.ParseString(string(body))
	if err != nil {
		return nil, fmt.Errorf("parse archived feed: %w", err)
	}
	var items []archivedItem
	for _, it := range feed.Items {
		if it == nil {
			continue
		}
		u := strings.TrimSpace(it.Link)
		title := strings.TrimSpace(it.Title)
		if u == "" || title == "" {
			continue
		}
		body := strings.TrimSpace(it.Description)
		if body == "" && it.Content != "" {
			body = strings.TrimSpace(it.Content)
		}
		if body == "" {
			// body_text is NOT NULL with length > 0; fall back to the
			// title so the row still encodes meaningful data.
			body = title
		}
		items = append(items, archivedItem{
			URL:         u,
			Title:       title,
			Body:        body,
			PublishedAt: pickPublished(it),
		})
	}
	return items, nil
}

func (c *ArchiveClient) httpGet(ctx context.Context, u string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("Accept", "application/json,application/xml,text/xml,*/*")
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("http status %d for %s", resp.StatusCode, u)
	}
	limited := io.LimitReader(resp.Body, 8<<20) // 8 MiB cap, archives can be larger
	return io.ReadAll(limited)
}

// evenSample returns up to n elements of in, spaced as evenly as
// possible. If len(in) <= n, returns the full slice. Deterministic.
func evenSample(in []string, n int) []string {
	if n <= 0 || len(in) == 0 {
		return nil
	}
	if len(in) <= n {
		out := make([]string, len(in))
		copy(out, in)
		return out
	}
	out := make([]string, 0, n)
	step := float64(len(in)) / float64(n)
	for i := 0; i < n; i++ {
		idx := int(float64(i) * step)
		if idx >= len(in) {
			idx = len(in) - 1
		}
		out = append(out, in[idx])
	}
	return out
}

// Errors for tests.
var (
	errArchiveEmpty = errors.New("archive returned empty payload")
)
