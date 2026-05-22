// Package rss is the news-RSS aggregator scraper. It fans out a configured
// list of Guatemalan outlets, fetches each feed (or, for Diario de Centro
// América, scrapes the homepage directly because DCA has no RSS), extracts
// the article body via a readability heuristic and UPSERTs rows into
// `news_articles` (UNIQUE on url, so re-runs are idempotent). Every run
// stamps a `scrape_runs` row keyed by SourceRSSAggregator so `/v1/health`
// (#14) can report ingest staleness.
//
// Outlets per docs/requirement.md Section B (RSS where available, direct
// scrape for DCA). Two Prensa Libre feeds are collapsed into the single
// "Prensa Libre" outlet; both URLs are listed and deduplicated by URL when
// the same article appears on both feeds.
package rss

// Outlet describes a single news source configured for the aggregator. For
// most outlets `FeedURLs` is set; for DCA `Direct` is set and `FeedURLs` is
// empty. Exactly one of the two must be populated.
type Outlet struct {
	// Name is the display + scrape_runs.source-suffix identifier. Stable
	// across runs; do not change without a migration of any dependent rows.
	Name string

	// FeedURLs are the RSS/Atom feed URLs. Multiple URLs are deduplicated
	// by article URL after parsing (Prensa Libre publishes two feeds with
	// overlap).
	FeedURLs []string

	// Direct is non-nil for outlets without RSS (DCA). It defines a single
	// HTML page to fetch and a CSS-style selector pattern to find article
	// links + extract body text.
	Direct *DirectConfig
}

// DirectConfig configures a direct-HTML scrape for outlets without RSS.
type DirectConfig struct {
	HomepageURL   string
	LinkSelector  string // goquery selector returning <a href> nodes
	BodySelector  string // goquery selector applied on the article page
	TitleSelector string // goquery selector applied on the article page
	URLAttr       string // "href" usually; allows future override
	IsArticleHref func(string) bool
	NormalizeHref func(string) string
}

// Sources returns the active outlets. Originally 10 per
// docs/requirement.md Section B; Soy502, Publinews and AGN were
// disabled in 2026-05 because their RSS endpoints have been
// decommissioned or never existed (see comments below). Prensa Libre
// exposes two feeds (general + politica); both are listed under the
// single "Prensa Libre" outlet and deduplicated by URL.
//
// Feed URLs are best-effort matches against feeds publicly indexed on each
// outlet's site or curated lists; if an outlet flips a path the entry can
// be updated without a code change.
func Sources() []Outlet {
	return []Outlet{
		{
			Name: "Prensa Libre",
			FeedURLs: []string{
				"https://www.prensalibre.com/feed/",
				"https://www.prensalibre.com/guatemala/politica/feed/",
			},
		},
		{
			Name:     "La Hora",
			FeedURLs: []string{"https://lahora.gt/feed/"},
		},
		// Soy502, Publinews, AGN — RSS endpoints decommissioned or never
		// existed as of 2026-05. Soy502's /rss.xml and /feed/ both 200 with
		// the Google consent shim instead of XML; Publinews returns 404 on
		// every common feed path; AGN's /feed/ now 301s to the homepage.
		// Re-enable only after confirming a working XML endpoint.
		{
			Name:     "Plaza Pública",
			FeedURLs: []string{"https://plazapublica.com.gt/feed/"},
		},
		{
			Name:     "Emisoras Unidas",
			FeedURLs: []string{"https://emisorasunidas.com/feed/"},
		},
		{
			Name:     "República",
			FeedURLs: []string{"https://republica.gt/feed/"},
		},
		{
			Name:     "Guatemala.com",
			FeedURLs: []string{"https://www.guatemala.com/feed/"},
		},
		{
			Name: "Diario de Centro América",
			Direct: &DirectConfig{
				HomepageURL:   "https://dca.gob.gt/noticias-guatemala-diario-centro-america/",
				LinkSelector:  "article a, h2 a, h3 a",
				BodySelector:  "article, .entry-content, .post-content, main",
				TitleSelector: "h1, .entry-title, .post-title",
				URLAttr:       "href",
				IsArticleHref: dcaIsArticleHref,
				NormalizeHref: dcaNormalizeHref,
			},
		},
	}
}
