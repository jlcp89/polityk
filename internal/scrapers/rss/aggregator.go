package rss

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/mmcdole/gofeed"
)

// SourceRSSAggregator is the scrape_runs.source identifier per the issue.
const SourceRSSAggregator = "rss_aggregator"

// DefaultUserAgent identifies this scraper per docs/requirement.md's
// "Operational guardrails" section ("identify yourself in the User-Agent").
// The form mirrors the example in that section.
const DefaultUserAgent = "PolitykForecastBot/0.1 (+https://github.com/jlcp89/polityk)"

const (
	defaultHTTPTimeout = 20 * time.Second
	// defaultMinDelay enforces ≤1 req/sec per outlet, with a small safety
	// margin so jitter inside the same second cannot violate the limit.
	defaultMinDelay = 1100 * time.Millisecond
	// defaultMaxBodyBytes caps article-body fetch size at 2 MiB. Long-form
	// pieces in Guatemalan dailies sit well under 200 KiB; this exists to
	// stop a runaway page from OOMing the scraper.
	defaultMaxBodyBytes int64 = 2 << 20
)

// Client is the configured RSS aggregator scraper. Tests inject Outlets +
// httptest.Server-rooted URLs + a faster MinDelay; production builds via
// NewDefaultClient.
type Client struct {
	HTTPClient   *http.Client
	UserAgent    string
	Outlets      []Outlet
	MinDelay     time.Duration
	MaxBodyBytes int64
	Logger       *slog.Logger

	// Clock returns the current time; tests inject a fixed clock. Defaults
	// to time.Now when nil.
	Clock func() time.Time
}

// NewDefaultClient builds the production scraper hitting the live feeds.
func NewDefaultClient() *Client {
	return &Client{
		HTTPClient:   &http.Client{Timeout: defaultHTTPTimeout},
		UserAgent:    DefaultUserAgent,
		Outlets:      Sources(),
		MinDelay:     defaultMinDelay,
		MaxBodyBytes: defaultMaxBodyBytes,
		Logger:       slog.Default(),
	}
}

// Run is the issue-contract entry point: fetch all configured outlets,
// extract bodies, UPSERT into news_articles, stamp scrape_runs (success or
// failure). Per-outlet errors are logged at WARN and do not abort the
// overall run; the run is considered successful if at least one outlet
// produced at least one article. Otherwise scrape_runs is stamped with the
// aggregated failure message so /v1/health surfaces the dead-source state.
func Run(ctx context.Context, db *sql.DB) error {
	return NewDefaultClient().Run(ctx, db)
}

// Run executes the configured Client.
func (c *Client) Run(ctx context.Context, db *sql.DB) error {
	if c.Logger == nil {
		c.Logger = slog.Default()
	}
	if c.Clock == nil {
		c.Clock = time.Now
	}
	if c.MaxBodyBytes <= 0 {
		c.MaxBodyBytes = defaultMaxBodyBytes
	}
	if len(c.Outlets) == 0 {
		err := errors.New("no outlets configured")
		_ = stampScrapeRun(ctx, db, SourceRSSAggregator, false, err.Error())
		return err
	}

	var totalInserted int
	var perOutletErrors []string
	for _, outlet := range c.Outlets {
		inserted, err := c.runOutlet(ctx, db, outlet)
		if err != nil {
			c.Logger.Warn("rss outlet failed",
				slog.String("outlet", outlet.Name),
				slog.String("error", err.Error()))
			perOutletErrors = append(perOutletErrors,
				fmt.Sprintf("%s: %s", outlet.Name, err.Error()))
			continue
		}
		totalInserted += inserted
		c.Logger.Info("rss outlet ok",
			slog.String("outlet", outlet.Name),
			slog.Int("inserted", inserted))
	}

	if totalInserted == 0 && len(perOutletErrors) == len(c.Outlets) {
		// Every outlet failed.
		msg := "all outlets failed: " + strings.Join(perOutletErrors, "; ")
		_ = stampScrapeRun(ctx, db, SourceRSSAggregator, false, msg)
		return errors.New(msg)
	}

	// Partial success counts as success: news ingestion is best-effort.
	// Surface the per-outlet failures in error_message so /v1/health can
	// expose the degraded state without forcing the next run to abort.
	errMsg := ""
	if len(perOutletErrors) > 0 {
		errMsg = "partial: " + strings.Join(perOutletErrors, "; ")
	}
	if err := stampScrapeRun(ctx, db, SourceRSSAggregator, true, errMsg); err != nil {
		return fmt.Errorf("stamp scrape_runs: %w", err)
	}
	return nil
}

// runOutlet handles one outlet end-to-end: fetch the feed (or homepage for
// Direct), parse items, fetch + extract bodies, UPSERT rows. Returns the
// number of newly inserted rows (existing rows under ON CONFLICT DO NOTHING
// do not increment the counter).
func (c *Client) runOutlet(ctx context.Context, db *sql.DB, outlet Outlet) (int, error) {
	if outlet.Direct != nil {
		return c.runDirect(ctx, db, outlet)
	}
	if len(outlet.FeedURLs) == 0 {
		return 0, fmt.Errorf("outlet %q has neither FeedURLs nor Direct", outlet.Name)
	}

	items, err := c.fetchAndParseFeeds(ctx, outlet)
	if err != nil {
		return 0, err
	}

	return c.ingestArticles(ctx, db, outlet, items)
}

// fetchedItem is the parser-agnostic representation passed to the body
// fetcher + writer. Built from gofeed.Item for RSS outlets and from
// goquery selections for the DCA direct scraper.
type fetchedItem struct {
	URL         string
	Title       string
	PublishedAt *time.Time
}

func (c *Client) fetchAndParseFeeds(ctx context.Context, outlet Outlet) ([]fetchedItem, error) {
	parser := gofeed.NewParser()
	parser.UserAgent = c.UserAgent
	parser.Client = c.HTTPClient

	var items []fetchedItem
	seen := map[string]bool{}
	var lastErr error
	for i, feedURL := range outlet.FeedURLs {
		if i > 0 {
			if err := sleepCtx(ctx, c.MinDelay); err != nil {
				return nil, err
			}
		}
		feed, err := parser.ParseURLWithContext(feedURL, ctx)
		if err != nil {
			lastErr = fmt.Errorf("parse %s: %w", feedURL, err)
			continue
		}
		for _, it := range feed.Items {
			if it == nil {
				continue
			}
			u := strings.TrimSpace(it.Link)
			if u == "" || seen[u] {
				continue
			}
			seen[u] = true
			items = append(items, fetchedItem{
				URL:         u,
				Title:       strings.TrimSpace(it.Title),
				PublishedAt: pickPublished(it),
			})
		}
	}
	if len(items) == 0 && lastErr != nil {
		return nil, lastErr
	}
	return items, nil
}

func pickPublished(it *gofeed.Item) *time.Time {
	if it.PublishedParsed != nil {
		t := it.PublishedParsed.UTC()
		return &t
	}
	if it.UpdatedParsed != nil {
		t := it.UpdatedParsed.UTC()
		return &t
	}
	return nil
}

func (c *Client) ingestArticles(ctx context.Context, db *sql.DB, outlet Outlet, items []fetchedItem) (int, error) {
	var inserted int
	for i, item := range items {
		if i > 0 {
			if err := sleepCtx(ctx, c.MinDelay); err != nil {
				return inserted, err
			}
		}
		if item.URL == "" {
			continue
		}
		body, title, err := c.fetchArticleBody(ctx, item.URL, item.Title)
		if err != nil {
			c.Logger.Warn("article fetch failed; skipping",
				slog.String("outlet", outlet.Name),
				slog.String("url", item.URL),
				slog.String("error", err.Error()))
			continue
		}
		body = strings.TrimSpace(body)
		if body == "" {
			c.Logger.Warn("article body empty after extraction; skipping",
				slog.String("outlet", outlet.Name),
				slog.String("url", item.URL))
			continue
		}
		if title == "" {
			title = item.Title
		}
		if strings.TrimSpace(title) == "" {
			// Title is NOT NULL — fall back to the host portion of the URL
			// rather than dropping the article (an empty headline is bad
			// metadata, not bad content).
			title = item.URL
		}
		n, err := insertArticle(ctx, db, outlet.Name, item.URL, title, body, item.PublishedAt)
		if err != nil {
			c.Logger.Warn("insert article failed; skipping",
				slog.String("outlet", outlet.Name),
				slog.String("url", item.URL),
				slog.String("error", err.Error()))
			continue
		}
		inserted += n
	}
	return inserted, nil
}

// fetchArticleBody hits the article URL, extracts the body via the shared
// readability heuristic, and returns the body and (if found) a refined
// title. Caller decides whether to fall back to the feed-supplied title.
func (c *Client) fetchArticleBody(ctx context.Context, url, _ string) (string, string, error) {
	body, err := c.fetchURL(ctx, url)
	if err != nil {
		return "", "", err
	}
	text, title := extractArticle(body)
	return text, title, nil
}

func (c *Client) fetchURL(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9")
	req.Header.Set("Accept-Language", "es-GT,es;q=0.9")
	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("http status %d", resp.StatusCode)
	}
	limited := io.LimitReader(resp.Body, c.MaxBodyBytes)
	return io.ReadAll(limited)
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

// insertArticle UPSERTs (outlet, url, title, body_text, published_at).
// Returns 1 if a new row was inserted, 0 if `url` already existed (ON
// CONFLICT DO NOTHING). published_at is nullable.
func insertArticle(ctx context.Context, db *sql.DB, outlet, url, title, body string, publishedAt *time.Time) (int, error) {
	if db == nil {
		return 0, nil
	}
	const stmt = `
        INSERT INTO news_articles (outlet, url, title, body_text, published_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (url) DO NOTHING
        RETURNING article_id
    `
	var id int64
	err := db.QueryRowContext(ctx, stmt, outlet, url, title, body, publishedAt).Scan(&id)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			// URL already present; idempotent re-run.
			return 0, nil
		}
		return 0, fmt.Errorf("insert news_articles: %w", err)
	}
	return 1, nil
}

// stampScrapeRun mirrors the helper from internal/scrapers/tse/parties.go.
// A separate copy avoids a circular package dependency and keeps each
// scraper independently testable. nil DB is a no-op for unit tests.
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

// rateLimitCounter is a test helper that records the number of HTTP
// requests issued and the wall-clock interval between consecutive ones. It
// is wired by passing the wrapped RoundTripper as Client.HTTPClient.Transport.
type rateLimitCounter struct {
	total atomic.Int64
}

func (rl *rateLimitCounter) RoundTrip(_ *http.Request) (*http.Response, error) {
	rl.total.Add(1)
	return nil, errors.New("rateLimitCounter is a counting-only transport")
}
