"""Manual intervention CLI per ADR-019.

Inserts a row into the `interventions` table and prints the generated
`intervention_id`. Both `--reason` and `--operator` are required and
must be non-empty. `--operator` defaults to ``$USER``; if neither is
provided the CLI errors out with exit code 2.

`--whatif` does NOT change the row that lands in `interventions` (the
schema has no whatif column per migration 0006_operational.sql); it
instead emits ``run_kind=whatif`` on stdout so the downstream forecast
trigger (#33) writes the next forecast as ``run_kind='whatif'``
(excluded from ``is_published``).

Usage::

    intervene.py \\
      --target-kind candidate \\
      --target-id 42 \\
      --kind disqualified \\
      --effective-at 2027-04-15T12:00:00-06:00 \\
      --reason "TSE Acuerdo NNNN-2027 disqualified candidate for ..." \\
      [--expires-at <ISO-8601>] \\
      [--override-probability 0.0] \\
      [--operator <name>] \\
      [--whatif]

Stdout on success::

    intervention_id=<n>
    run_kind=whatif        # only when --whatif is passed

The CLI surfaces `override_probability` out-of-range as a clean
``argparse`` error (exit 2) before any DB round-trip. The DB
`CHECK` constraint catches the same case as a defense in depth, so
the schema is the source of truth.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Any, cast

logger = logging.getLogger(__name__)

TARGET_KINDS = ("candidate", "party", "race")
INTERVENTION_KINDS = (
    "disqualified",
    "withdrew",
    "party_cancelled",
    "manual_probability",
)


def _nonempty(s: str) -> str:
    """argparse type: reject empty strings.

    Used for `--reason` and `--operator` so empty quoted values like
    ``--reason ""`` are rejected before they hit the DB CHECK.
    """
    if s == "" or s.strip() == "":
        raise argparse.ArgumentTypeError("must be non-empty")
    return s


def _probability(s: str) -> float:
    """argparse type: parse a float in [0, 1]."""
    try:
        v = float(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a float: {s!r}") from exc
    if v < 0.0 or v > 1.0:
        raise argparse.ArgumentTypeError(
            f"must be in [0, 1] (got {v})"
        )
    return v


def _iso8601(s: str) -> datetime:
    """argparse type: parse an ISO-8601 timestamp.

    `datetime.fromisoformat` accepts the offset-aware shape used by the
    CLI's documented examples (``2027-04-15T12:00:00-06:00``) since
    Python 3.11.
    """
    try:
        return datetime.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not a valid ISO-8601 timestamp: {s!r}"
        ) from exc


def _resolve_operator(operator_arg: str | None) -> str:
    """Return `--operator` if set; else `$USER` if non-empty; else error.

    Encapsulates the acceptance-criterion "rejects missing --operator
    and $USER empty" so the CLI fails cleanly with exit 2 rather than
    letting the DB CHECK trip.
    """
    if operator_arg is not None and operator_arg.strip():
        return operator_arg
    user = os.environ.get("USER", "")
    if not user.strip():
        raise SystemExit(
            "intervene: --operator is required when $USER is empty"
        )
    return user


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intervene",
        description=(
            "Insert an interventions row per ADR-019. Requires --reason; "
            "--operator defaults to $USER. Use --whatif to mark the next "
            "forecast as run_kind='whatif'."
        ),
    )
    parser.add_argument(
        "--target-kind",
        required=True,
        choices=TARGET_KINDS,
        help="one of candidate | party | race (matches the DB enum)",
    )
    parser.add_argument(
        "--target-id",
        required=True,
        type=int,
        help="BIGINT FK into the matching dim table (caller's responsibility)",
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=INTERVENTION_KINDS,
        help="one of disqualified | withdrew | party_cancelled | manual_probability",
    )
    parser.add_argument(
        "--effective-at",
        required=True,
        type=_iso8601,
        help="ISO-8601 timestamp when the intervention becomes active",
    )
    parser.add_argument(
        "--expires-at",
        type=_iso8601,
        default=None,
        help="optional ISO-8601 timestamp when the intervention stops applying",
    )
    parser.add_argument(
        "--override-probability",
        type=_probability,
        default=None,
        help=(
            "required for kind=manual_probability; must be in [0, 1]. "
            "Rejected for other kinds by the DB CHECK."
        ),
    )
    parser.add_argument(
        "--reason",
        required=True,
        type=_nonempty,
        help="non-empty audit string; rejected if empty",
    )
    parser.add_argument(
        "--operator",
        type=_nonempty,
        default=None,
        help="defaults to $USER; CLI errors if both are empty",
    )
    parser.add_argument(
        "--whatif",
        action="store_true",
        help=(
            "mark the next forecast as run_kind='whatif' (excluded from "
            "is_published). Does not change the interventions row."
        ),
    )
    return parser


def insert_intervention(
    conn: Any,
    *,
    target_kind: str,
    target_id: int,
    kind: str,
    effective_at: datetime,
    reason: str,
    operator: str,
    expires_at: datetime | None = None,
    override_probability: float | None = None,
) -> int:
    """Insert a row into `interventions` and return `intervention_id`.

    The caller is responsible for `conn.commit()`. This split keeps
    integration tests able to wrap the call in a transaction that
    rolls back, as required by the issue's acceptance criteria.

    Raises whatever `psycopg` raises on a constraint violation —
    `override_probability` outside [0, 1], missing reason/operator,
    invalid kind/target_kind enum value, etc. The CLI surfaces these
    cleanly via `main`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO interventions
                (target_kind, target_id, kind, effective_at, expires_at,
                 override_probability, reason, operator)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING intervention_id
            """,
            (
                target_kind,
                target_id,
                kind,
                effective_at,
                expires_at,
                override_probability,
                reason,
                operator,
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            "insert_intervention: INSERT...RETURNING returned no row"
        )
    return cast(int, row[0])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    parser = _build_parser()
    args = parser.parse_args(argv)

    operator = _resolve_operator(args.operator)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    import psycopg

    try:
        with psycopg.connect(dsn) as conn:
            intervention_id = insert_intervention(
                conn,
                target_kind=args.target_kind,
                target_id=args.target_id,
                kind=args.kind,
                effective_at=args.effective_at,
                expires_at=args.expires_at,
                override_probability=args.override_probability,
                reason=args.reason,
                operator=operator,
            )
            conn.commit()
    except psycopg.errors.CheckViolation as exc:
        # DB-side defense in depth for override_probability range, empty
        # reason/operator, and the manual_probability/override_probability
        # contract. Surface a clean error instead of a stack trace.
        logger.error("intervene: DB CHECK rejected the row: %s", exc)
        return 1
    except psycopg.errors.DataError as exc:
        # Unknown enum value for target_kind / kind.
        logger.error("intervene: DB rejected the row: %s", exc)
        return 1

    print(f"intervention_id={intervention_id}")
    if args.whatif:
        print("run_kind=whatif")
    return 0


__all__ = [
    "INTERVENTION_KINDS",
    "TARGET_KINDS",
    "insert_intervention",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
