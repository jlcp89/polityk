"""Smoke test that proves the package is importable under pytest.

Real tests land alongside each pipeline module (scrapers, parsers, models)
in their own files.
"""

from __future__ import annotations

import pipeline


def test_version_string() -> None:
    assert isinstance(pipeline.__version__, str)
    assert pipeline.__version__
