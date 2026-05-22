package macro

import (
	"context"
	"database/sql"
	"fmt"
	"io"
	"log/slog"
	"net/http"
)

// RunStats is the per-source summary returned by Client.Run.
type RunStats struct {
	Source   string
	Fetched  int // rows parsed from feed
	Inserted int // rows newly written (duplicates excluded)
}

// Client is the configurable scraper used by every macro source. Source +
// FeedURL are populated by the source-specific constructors (NewBanguatClient,
// NewINEClient, NewSEGEPLANClient, NewMINFINClient). Tests override FeedURL
// to point at an httptest.Server.
type Client struct {
	Source     string
	FeedURL    string
	HTTPClient *http.Client
	UserAgent  string
	Logger     *slog.Logger
}

// NewBanguatClient targets Banco de Guatemala's open-data CSV export for
// macroeconomic series (GDP YoY growth, inflation YoY, remittance inflow YoY).
// The default URL points at the official statistics portal; override for
// testing.
func NewBanguatClient() *Client {
	return &Client{
		Source:     SourceBanguat,
		FeedURL:    "https://www.banguat.gob.gt/datos-abiertos/macro/indicators.csv",
		HTTPClient: newHTTPClient(),
		UserAgent:  DefaultUserAgent,
		Logger:     slog.Default(),
	}
}

// NewINEClient targets Instituto Nacional de Estadística open-data exports
// (homicide-rate YoY, padrón demographics).
func NewINEClient() *Client {
	return &Client{
		Source:     SourceINE,
		FeedURL:    "https://www.ine.gob.gt/datos-abiertos/indicators.csv",
		HTTPClient: newHTTPClient(),
		UserAgent:  DefaultUserAgent,
		Logger:     slog.Default(),
	}
}

// NewSEGEPLANClient targets Secretaría de Planificación open-data exports
// (the official planning indicators selected per the fundamentals layer).
func NewSEGEPLANClient() *Client {
	return &Client{
		Source:     SourceSEGEPLAN,
		FeedURL:    "https://www.segeplan.gob.gt/datos-abiertos/indicators.csv",
		HTTPClient: newHTTPClient(),
		UserAgent:  DefaultUserAgent,
		Logger:     slog.Default(),
	}
}

// NewMINFINClient targets Ministerio de Finanzas open-data exports
// (fiscal-balance YoY; optional v1).
func NewMINFINClient() *Client {
	return &Client{
		Source:     SourceMINFIN,
		FeedURL:    "https://www.minfin.gob.gt/datos-abiertos/indicators.csv",
		HTTPClient: newHTTPClient(),
		UserAgent:  DefaultUserAgent,
		Logger:     slog.Default(),
	}
}

// Run fetches the configured CSV feed, parses it, UPSERTs the resulting
// indicators into macro_indicators, and stamps scrape_runs. A failed run
// still stamps scrape_runs (success=false, error_message=err.Error()) so
// /v1/health (#14) can flag the source as stale.
func (c *Client) Run(ctx context.Context, db *sql.DB) (RunStats, error) {
	if c.Logger == nil {
		c.Logger = slog.Default()
	}

	stats, err := c.runOnce(ctx, db)
	if err != nil {
		if stampErr := StampScrapeRun(ctx, db, c.Source, false, err.Error()); stampErr != nil {
			c.Logger.Warn("macro: stamp scrape_runs after failure",
				slog.String("source", c.Source),
				slog.String("error", stampErr.Error()))
		}
		return stats, err
	}
	if err := StampScrapeRun(ctx, db, c.Source, true, ""); err != nil {
		return stats, fmt.Errorf("stamp scrape_runs: %w", err)
	}
	c.Logger.Info("macro: scrape ok",
		slog.String("source", c.Source),
		slog.Int("fetched", stats.Fetched),
		slog.Int("inserted", stats.Inserted))
	return stats, nil
}

func (c *Client) runOnce(ctx context.Context, db *sql.DB) (RunStats, error) {
	stats := RunStats{Source: c.Source}
	body, err := c.fetch(ctx)
	if err != nil {
		return stats, fmt.Errorf("fetch: %w", err)
	}
	defer func() { _ = body.Close() }()

	rows, err := ParseCSV(body, c.Source)
	if err != nil {
		return stats, fmt.Errorf("parse: %w", err)
	}
	stats.Fetched = len(rows)

	inserted, err := Upsert(ctx, db, rows)
	if err != nil {
		return stats, fmt.Errorf("upsert: %w", err)
	}
	stats.Inserted = inserted
	return stats, nil
}

func (c *Client) fetch(ctx context.Context) (io.ReadCloser, error) {
	if c.FeedURL == "" {
		return nil, fmt.Errorf("empty FeedURL for source %q", c.Source)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.FeedURL, nil)
	if err != nil {
		return nil, err
	}
	ua := c.UserAgent
	if ua == "" {
		ua = DefaultUserAgent
	}
	req.Header.Set("User-Agent", ua)
	req.Header.Set("Accept", "text/csv,text/plain")
	req.Header.Set("Accept-Language", "es-GT,es;q=0.9")

	client := c.HTTPClient
	if client == nil {
		client = newHTTPClient()
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_ = resp.Body.Close()
		return nil, fmt.Errorf("http status %d", resp.StatusCode)
	}
	return resp.Body, nil
}
