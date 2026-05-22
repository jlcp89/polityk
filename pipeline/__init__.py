"""polityk Python ML + scraping pipeline.

Per ADR-001 (stdlib-first) and ADR-010 (goose owns all schema migrations),
this package does NOT manage schema. It reads/writes the Postgres database
whose migrations live in `migrations/` at the repo root.
"""

__version__ = "0.0.1"
