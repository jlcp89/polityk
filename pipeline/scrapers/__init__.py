"""polityk scrapers and bulk loaders.

Per ADR-004 the live HTTP scrapers run in Go; this Python package holds
PDF / Excel / provisional-source loaders that need pdfplumber / pandas /
openpyxl and would be awkward in Go.

Each scraper / loader writes a row into the `scrape_runs` audit table on
every successful run, keyed by a stable `source` string.
"""
