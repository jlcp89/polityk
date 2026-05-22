"""Python scrapers (Memoria PDFs, TSE provisional ingest, etc.).

Per ADR-004 the live HTTP scrapers run in Go; this Python package holds
PDF / Excel / provisional-source loaders that need pdfplumber / pandas /
openpyxl and would be awkward in Go.
"""
