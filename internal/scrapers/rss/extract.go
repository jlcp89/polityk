package rss

import (
	"bytes"
	"regexp"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

// articleBodySelectors are tried in order; the first non-empty match wins.
// Real Guatemalan outlets use a small set of CMS patterns (WordPress's
// .entry-content, custom .post-content, semantic <article>); falling back
// to <main> catches the long-tail. Anything matched first is treated as
// authoritative and other candidates are ignored.
var articleBodySelectors = []string{
	"article .entry-content",
	"article .post-content",
	"article .article-content",
	".entry-content",
	".post-content",
	".article-content",
	".article__body",
	"article",
	"main",
}

var articleTitleSelectors = []string{
	"h1.entry-title",
	"h1.post-title",
	"h1.article-title",
	"article h1",
	"main h1",
	"h1",
}

// stripNoise removes nodes from a goquery document that almost never
// contain real article text. Done before extracting so a chrome <script>
// or navigation block can't poison the body.
func stripNoise(doc *goquery.Document) {
	for _, sel := range []string{
		"script", "style", "noscript", "iframe",
		"nav", "header", "footer", "aside",
		"form", "button",
		".social-share", ".share-buttons", ".related-articles",
		".advertisement", ".ad", ".ads", ".ad-container",
		".comments", "#comments",
		".breadcrumb",
		"figure figcaption",
	} {
		doc.Find(sel).Remove()
	}
}

// extractArticle parses the given HTML and returns (bodyText, title). If
// no body candidate yields any meaningful text, returns ("", title) so the
// caller skips the article rather than inserting an empty row. Extraction
// is deliberately conservative: we never fall back to <body> as a whole
// because that pulls in too much site chrome on outlets without a clean
// content container.
func extractArticle(html []byte) (string, string) {
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(html))
	if err != nil {
		return "", ""
	}
	stripNoise(doc)

	title := ""
	for _, sel := range articleTitleSelectors {
		if t := strings.TrimSpace(doc.Find(sel).First().Text()); t != "" {
			title = collapseWhitespace(t)
			break
		}
	}

	body := ""
	for _, sel := range articleBodySelectors {
		container := doc.Find(sel).First()
		if container.Length() == 0 {
			continue
		}
		text := paragraphsToText(container)
		if text == "" {
			text = collapseWhitespace(strings.TrimSpace(container.Text()))
		}
		if text != "" {
			body = text
			break
		}
	}
	return body, title
}

// paragraphsToText prefers an article container's <p> nodes (real article
// paragraphs) and falls back to the container's flat text. <p>-based
// extraction yields cleaner output than slicing the whole subtree because
// it drops widget/menu DIVs interspersed in the layout.
func paragraphsToText(container *goquery.Selection) string {
	ps := container.Find("p")
	if ps.Length() == 0 {
		return ""
	}
	var parts []string
	ps.Each(func(_ int, p *goquery.Selection) {
		t := collapseWhitespace(strings.TrimSpace(p.Text()))
		if t == "" {
			return
		}
		parts = append(parts, t)
	})
	return strings.Join(parts, "\n\n")
}

var whitespaceRe = regexp.MustCompile(`\s+`)

func collapseWhitespace(s string) string {
	return strings.TrimSpace(whitespaceRe.ReplaceAllString(s, " "))
}
