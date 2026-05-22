package rss

import (
	"bytes"
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"net/url"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

// dcaIsArticleHref reports whether a homepage link looks like an article
// permalink rather than a section index, tag page, or external link. DCA's
// article URLs follow the WordPress slug convention under
// dca.gob.gt/<slug>/ — we filter out the obvious section prefixes.
func dcaIsArticleHref(href string) bool {
	if href == "" {
		return false
	}
	if strings.HasPrefix(href, "#") || strings.HasPrefix(href, "mailto:") {
		return false
	}
	for _, skip := range []string{
		"/category/", "/tag/", "/author/", "/wp-content/",
		"/wp-admin/", "/wp-login.php", "/feed/", "/page/",
	} {
		if strings.Contains(href, skip) {
			return false
		}
	}
	// Has to either be a relative path or an absolute URL on dca.gob.gt.
	if strings.HasPrefix(href, "http") {
		u, err := url.Parse(href)
		if err != nil {
			return false
		}
		if !strings.HasSuffix(u.Host, "dca.gob.gt") {
			return false
		}
	}
	return true
}

// dcaNormalizeHref resolves a possibly-relative href against the DCA
// homepage base so we always store a fully-qualified URL.
func dcaNormalizeHref(href string) string {
	base, err := url.Parse("https://dca.gob.gt/")
	if err != nil {
		return href
	}
	ref, err := url.Parse(href)
	if err != nil {
		return href
	}
	return base.ResolveReference(ref).String()
}

// runDirect handles outlets whose homepage we scrape directly (DCA). It
// fetches the homepage, extracts candidate article links, dedupes them,
// fetches each article, runs the same body extractor as the RSS path, and
// UPSERTs rows. Behaves identically to runOutlet from there.
func (c *Client) runDirect(ctx context.Context, db *sql.DB, outlet Outlet) (int, error) {
	if outlet.Direct == nil {
		return 0, fmt.Errorf("outlet %q: runDirect called without Direct config", outlet.Name)
	}
	cfg := outlet.Direct

	homepage, err := c.fetchURL(ctx, cfg.HomepageURL)
	if err != nil {
		return 0, fmt.Errorf("fetch homepage %s: %w", cfg.HomepageURL, err)
	}
	items, err := parseDirectHomepage(homepage, cfg)
	if err != nil {
		return 0, fmt.Errorf("parse homepage %s: %w", cfg.HomepageURL, err)
	}
	if len(items) == 0 {
		c.Logger.Warn("direct outlet found zero article links",
			slog.String("outlet", outlet.Name),
			slog.String("homepage", cfg.HomepageURL))
	}
	return c.ingestArticles(ctx, db, outlet, items)
}

// parseDirectHomepage extracts article-link items from a homepage HTML
// document using cfg.LinkSelector, applying cfg.IsArticleHref + cfg.NormalizeHref
// to filter and normalize. Title is taken from the link text and may be
// overridden by the article page's own <h1> at fetch time.
func parseDirectHomepage(html []byte, cfg *DirectConfig) ([]fetchedItem, error) {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(html))
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var items []fetchedItem
	doc.Find(cfg.LinkSelector).Each(func(_ int, s *goquery.Selection) {
		attr := cfg.URLAttr
		if attr == "" {
			attr = "href"
		}
		href, ok := s.Attr(attr)
		if !ok {
			return
		}
		href = strings.TrimSpace(href)
		if cfg.IsArticleHref != nil && !cfg.IsArticleHref(href) {
			return
		}
		if cfg.NormalizeHref != nil {
			href = cfg.NormalizeHref(href)
		}
		if href == "" || seen[href] {
			return
		}
		seen[href] = true
		items = append(items, fetchedItem{
			URL:   href,
			Title: collapseWhitespace(strings.TrimSpace(s.Text())),
		})
	})
	return items, nil
}
