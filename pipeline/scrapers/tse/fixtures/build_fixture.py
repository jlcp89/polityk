"""Regenerate `tse_2019_presidential.xlsx`.

Run with:
    uv run python -m pipeline.scrapers.tse.fixtures.build_fixture

Synthetic dataset:
- 3 GT-01 (Guatemala dept) municipalities: 0101 Guatemala, 0102 Santa
  Catarina Pinula, 0103 San José Pinula
- Round 1: 5 candidates (top of the actual 2019 first-round field)
- Round 2: 2 candidates (the actual 2019 runoff pair)

Vote counts are *not* the real 2019 numbers — they are the fixture-only
totals that the integration test asserts against. The published TSE
totals are passed into `load(expected_round{1,2}_total=...)` separately
when a maintainer runs against real data.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

OUTPUT_PATH = Path(__file__).parent / "tse_2019_presidential.xlsx"

HEADER = ("round", "dept_code", "muni_code", "candidate_full_name", "votes")

ROUND_1_ROWS: list[tuple[int, str, str, str, int]] = [
    (1, "01", "0101", "Sandra Torres", 120000),
    (1, "01", "0101", "Alejandro Giammattei", 80000),
    (1, "01", "0101", "Edmond Mulet", 60000),
    (1, "01", "0101", "Thelma Cabrera", 40000),
    (1, "01", "0101", "Roberto Arzú", 20000),
    (1, "01", "0102", "Sandra Torres", 8000),
    (1, "01", "0102", "Alejandro Giammattei", 15000),
    (1, "01", "0102", "Edmond Mulet", 7000),
    (1, "01", "0102", "Thelma Cabrera", 3000),
    (1, "01", "0102", "Roberto Arzú", 2000),
    (1, "01", "0103", "Sandra Torres", 6000),
    (1, "01", "0103", "Alejandro Giammattei", 5000),
    (1, "01", "0103", "Edmond Mulet", 2500),
    (1, "01", "0103", "Thelma Cabrera", 1500),
    (1, "01", "0103", "Roberto Arzú", 1000),
]

ROUND_2_ROWS: list[tuple[int, str, str, str, int]] = [
    (2, "01", "0101", "Sandra Torres", 90000),
    (2, "01", "0101", "Alejandro Giammattei", 130000),
    (2, "01", "0102", "Sandra Torres", 7000),
    (2, "01", "0102", "Alejandro Giammattei", 18000),
    (2, "01", "0103", "Sandra Torres", 5500),
    (2, "01", "0103", "Alejandro Giammattei", 7500),
]

# These two constants are imported by the test to assert that the loader
# correctly sums to the fixture's known totals. They represent what TSE
# would have published as the "national total" for this dataset.
EXPECTED_ROUND_1_TOTAL = sum(r[4] for r in ROUND_1_ROWS)  # 371000
EXPECTED_ROUND_2_TOTAL = sum(r[4] for r in ROUND_2_ROWS)  # 258000


def build(path: Path = OUTPUT_PATH) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "results"
    ws.append(list(HEADER))
    for row in ROUND_1_ROWS:
        ws.append(list(row))
    for row in ROUND_2_ROWS:
        ws.append(list(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def main() -> None:
    out = build()
    print(f"wrote {out}")
    print(f"round 1 total: {EXPECTED_ROUND_1_TOTAL}")
    print(f"round 2 total: {EXPECTED_ROUND_2_TOTAL}")


if __name__ == "__main__":
    main()
