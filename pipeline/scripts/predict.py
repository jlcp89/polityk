"""Forecast writer (issue #33, ADR-006, ADR-014).

Pure orchestration: run the presidential combiner (#32), build the ADR-014
quantile payload, INSERT one row into ``forecasts`` and one into
``posterior_archives`` (full sample matrix), then ``NOTIFY forecast_ready``
with the new ``run_id`` so the Go listener (#10) can clear its LRU.

``is_published`` always stays FALSE on insert — the calibration gate (#36)
flips it later. The same row is written for ``run_kind='scheduled'`` and
``run_kind='whatif'``; only ``run_kind='scheduled'`` is eligible for
publication (the partial index on ``forecasts.is_published`` already filters
by ``race_type``).

The module is split into pure-logic helpers (payload construction, sample-
array conversion) and a thin DB writer so the test suite can exercise the
ADR-014 contract without a Postgres instance, and the integration test can
exercise the full write + NOTIFY round-trip without re-running the PyMC
fit. The library entry point :func:`produce_forecast` accepts a pre-built
:class:`PresidentialPosterior` so callers can inject a deterministic
synthetic posterior in tests; only :func:`main` runs the combiner itself.

Usage::

    uv run python pipeline/scripts/predict.py \\
        --cycle 2027 --round 1

The CLI prints ``run_id=<uuid>`` on success.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pipeline.models.interventions import (
    Intervention,
    apply_interventions,
    load_active_interventions,
)
from pipeline.models.presidential import (
    QUANTILE_LEVELS,
    PresidentialPosterior,
)

logger = logging.getLogger(__name__)

# ---- ADR-014 constants ----------------------------------------------------

#: Model version stamped into every forecast row. Bumped in lockstep with the
#: methodology URL fragment so ``/v1/methodology`` and ``forecasts.payload``
#: stay aligned.
MODEL_VERSION: str = "0.1.0"

#: Public methodology URL per ADR-014. The fragment carries the model
#: version so older payloads still resolve to the methodology version that
#: produced them.
METHODOLOGY_URL: str = "https://polityk.gt/methodology#presidential-0.1.0"

#: race_type discriminator used on both `forecasts.race_type` and
#: `posterior_archives.race_type`.
RACE_TYPE_PRESIDENTIAL: str = "presidential"

#: LISTEN/NOTIFY channel; matches `listener.Channel` in the Go side.
NOTIFY_CHANNEL: str = "forecast_ready"


# ---- Payload construction (pure logic) ------------------------------------


def _quantile_keys() -> tuple[str, ...]:
    """Quantile keys in the order they appear in the ADR-014 payload.

    Keys are formatted ``pNN`` (no trailing zero), matching the example in
    ADR-014. Pulled from :data:`QUANTILE_LEVELS` so the combiner and the
    payload writer can never drift out of sync.
    """
    out: list[str] = []
    for lvl in QUANTILE_LEVELS:
        pct = int(round(lvl * 100))
        out.append(f"p{pct:02d}")
    return tuple(out)


QUANTILE_KEYS: tuple[str, ...] = _quantile_keys()


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    """One ``candidates[i]`` entry per ADR-014.

    ``candidate`` is a :class:`pipeline.models.presidential.CandidatePosterior`;
    its ``vote_share_quantiles`` is a ``{level: float}`` dict keyed by the
    raw 0.05/0.10/... levels — we re-key to the ``p05`` string form on the
    way out.
    """
    quantiles = candidate.vote_share_quantiles
    vote_share: dict[str, float] = {}
    for lvl, key in zip(QUANTILE_LEVELS, QUANTILE_KEYS, strict=True):
        # The combiner stores levels as floats; tolerate either the raw
        # float or a pre-rounded variant by looking up via both.
        if lvl in quantiles:
            vote_share[key] = float(quantiles[lvl])
        else:  # defensive — every level is required by ADR-014
            raise KeyError(f"missing quantile level {lvl} on candidate {candidate.candidate_id}")
    return {
        "candidate_id": int(candidate.candidate_id),
        "name": str(candidate.name),
        "wikidata_qid": candidate.wikidata_qid,
        "party_id": candidate.party_id,
        "party_name": candidate.party_name,
        "vote_share": vote_share,
        "win_probability_round1": float(candidate.win_probability_round1),
        "qualifies_for_runoff_probability": float(
            candidate.qualifies_for_runoff_probability
        ),
    }


def _runoff_entry_payload(entry: Any) -> dict[str, Any]:
    return {
        "candidate_a_id": int(entry.a_candidate_id),
        "candidate_b_id": int(entry.b_candidate_id),
        "pair_probability": float(entry.pair_probability),
        "winner_a_probability": float(entry.winner_a_probability),
    }


def build_presidential_payload(
    posterior: PresidentialPosterior,
    *,
    run_id: uuid.UUID,
    generated_at: datetime,
    model_version: str = MODEL_VERSION,
    methodology_url: str = METHODOLOGY_URL,
    cycle: int = 2027,
    round_: int = 1,
    interventions_applied: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the ADR-014 canonical presidential payload.

    Everything in the returned dict — apart from ``run_id`` and
    ``generated_at`` — is a deterministic function of ``posterior``,
    ``model_version``, ``methodology_url``, ``cycle``, ``round_``, and
    ``interventions_applied``. That gives the issue-#33 idempotence guarantee:
    on a fixed-seed posterior re-running the combiner produces the same
    payload bytes once those two timestamp/uuid fields are factored out.

    ``interventions_applied`` is the audit-trail array required by ADR-019;
    the applier in :mod:`pipeline.models.interventions` builds it. Defaults
    to an empty list when no interventions are active.
    """
    if round_ not in (1, 2):
        raise ValueError(f"round_ must be 1 or 2, got {round_}")
    if not posterior.candidates:
        raise ValueError("posterior has no candidates")

    return {
        "run_id": str(run_id),
        "model_version": model_version,
        "generated_at": _format_iso8601_utc(generated_at),
        "race": {"type": RACE_TYPE_PRESIDENTIAL, "cycle": int(cycle), "round": int(round_)},
        "candidates": [_candidate_payload(c) for c in posterior.candidates],
        "runoff_matrix": [_runoff_entry_payload(e) for e in posterior.runoff_matrix],
        "interventions_applied": list(interventions_applied or []),
        "methodology_url": methodology_url,
    }


def _format_iso8601_utc(dt: datetime) -> str:
    """Format ``dt`` as ISO-8601 with explicit UTC offset (``+00:00``).

    Naive datetimes are rejected — the writer must emit timezone-aware
    timestamps so the Android client (`generated_at` parser) doesn't have
    to guess offsets.
    """
    if dt.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return dt.astimezone(UTC).isoformat()


# ---- Posterior sample matrix (pure logic) ---------------------------------


def posterior_sample_array(posterior: PresidentialPosterior) -> list[list[float]]:
    """Convert ``first_round_samples`` to a 2-D list-of-lists for psycopg.

    Postgres ``NUMERIC[][]`` round-trips through psycopg as a nested Python
    sequence. A list-of-lists of floats is the canonical binding shape and
    keeps the test fakes simple (they can compare equality without numpy).
    """
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(posterior.first_round_samples, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"first_round_samples must be 2-D (n_mc, n_candidates), got shape {arr.shape}"
        )
    return [[float(x) for x in row] for row in arr]


# ---- DB writer ------------------------------------------------------------


def write_forecast(
    conn: Any,
    *,
    run_id: uuid.UUID,
    model_version: str,
    generated_at: datetime,
    payload: dict[str, Any],
    sample_array: list[list[float]],
    race_type: str = RACE_TYPE_PRESIDENTIAL,
    run_kind: str = "scheduled",
) -> None:
    """Insert one ``forecasts`` row + one ``posterior_archives`` row, NOTIFY.

    Caller owns the transaction (no implicit ``commit()`` — :func:`main`
    commits after the call returns; the integration test wraps the call in
    a transaction and rolls back). The NOTIFY fires inside the same
    transaction; per Postgres semantics it is queued until commit so the
    Go listener receives it exactly once when the writer commits.

    ``is_published`` is always FALSE on insert (the table default). The
    calibration gate (#36) flips it later if all C1-C6 gates pass.
    """
    if run_kind not in ("scheduled", "whatif"):
        raise ValueError(f"run_kind must be 'scheduled' or 'whatif', got {run_kind!r}")
    payload_json = json.dumps(payload)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecasts
                (run_id, model_version, generated_at, race_type, run_kind, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                str(run_id),
                model_version,
                generated_at,
                race_type,
                run_kind,
                payload_json,
            ),
        )
        cur.execute(
            """
            INSERT INTO posterior_archives (run_id, race_type, sample_array)
            VALUES (%s, %s, %s)
            """,
            (str(run_id), race_type, sample_array),
        )
        # pg_notify is preferred over `NOTIFY` because it accepts a payload
        # safely as a parameter (no SQL string-construction with run_id).
        cur.execute(
            "SELECT pg_notify(%s, %s)",
            (NOTIFY_CHANNEL, str(run_id)),
        )


# ---- Library entry point --------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ForecastWriteResult:
    """Returned by :func:`produce_forecast`; used by the CLI and the tests."""

    run_id: uuid.UUID
    generated_at: datetime
    payload: dict[str, Any]


def produce_forecast(
    conn: Any,
    *,
    posterior: PresidentialPosterior,
    run_id: uuid.UUID | None = None,
    generated_at: datetime | None = None,
    model_version: str = MODEL_VERSION,
    methodology_url: str = METHODOLOGY_URL,
    cycle: int = 2027,
    round_: int = 1,
    run_kind: str = "scheduled",
    interventions: Sequence[Intervention] | None = None,
) -> ForecastWriteResult:
    """Build the ADR-014 payload and write both forecast rows.

    Generates a fresh UUIDv4 ``run_id`` and a UTC timestamp when those are
    not supplied; tests pin both for reproducibility. Caller commits.

    ``interventions`` controls the ADR-019 applier behaviour:

    * ``None``  — load active interventions from ``conn`` via
      :func:`pipeline.models.interventions.load_active_interventions` and
      apply them. This is the production CLI path.
    * ``[]``    — skip the load entirely (no DB SELECT), no transformation.
      Tests use this to keep the fake-conn path schema-free.
    * non-empty — use the provided interventions directly; no DB read.

    The ``forecasts.payload`` written downstream carries the resolved
    ``interventions_applied`` array regardless of which branch ran.
    """
    rid = run_id if run_id is not None else uuid.uuid4()
    gen_at = generated_at if generated_at is not None else datetime.now(UTC)

    if interventions is None:
        active = load_active_interventions(conn, at=gen_at)
    else:
        active = list(interventions)

    transformed_posterior, interventions_applied = apply_interventions(
        posterior, active
    )

    payload = build_presidential_payload(
        transformed_posterior,
        run_id=rid,
        generated_at=gen_at,
        model_version=model_version,
        methodology_url=methodology_url,
        cycle=cycle,
        round_=round_,
        interventions_applied=interventions_applied,
    )
    sample_array = posterior_sample_array(transformed_posterior)
    write_forecast(
        conn,
        run_id=rid,
        model_version=model_version,
        generated_at=gen_at,
        payload=payload,
        sample_array=sample_array,
        race_type=RACE_TYPE_PRESIDENTIAL,
        run_kind=run_kind,
    )
    return ForecastWriteResult(run_id=rid, generated_at=gen_at, payload=payload)


# ---- CLI ------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="predict",
        description=(
            "Run the presidential combiner (#32), build the ADR-014 quantile "
            "payload, write forecasts + posterior_archives, and emit "
            "NOTIFY forecast_ready. is_published stays FALSE until the "
            "calibration gate (#36) approves it."
        ),
    )
    parser.add_argument(
        "--cycle", type=int, default=2027, help="Election cycle (default 2027)"
    )
    parser.add_argument(
        "--round",
        dest="round_",
        type=int,
        default=1,
        choices=(1, 2),
        help="Election round (default 1)",
    )
    parser.add_argument(
        "--run-kind",
        choices=("scheduled", "whatif"),
        default="scheduled",
        help="Forecast run kind (default 'scheduled'). 'whatif' is excluded from is_published.",
    )
    parser.add_argument(
        "--model-version",
        default=MODEL_VERSION,
        help=f"Model version string (default {MODEL_VERSION!r})",
    )
    parser.add_argument(
        "--methodology-url",
        default=METHODOLOGY_URL,
        help="Public methodology URL written into payload.methodology_url",
    )
    return parser


def _load_inputs_from_db(_conn: Any) -> PresidentialPosterior:
    """Stub for the production fit path. Not implemented in this iteration.

    The combiner (#32) takes an ``AggregatorPosterior`` + ``FundamentalsCoefficients``
    + candidate inputs + runoff history. Producing these from the database
    requires the poll-aggregator loader (#30 follow-up) and the fundamentals
    feature loader (#31 follow-up). Issue #33 ships the writer layer; the
    real load path is a separate ticket.
    """
    raise NotImplementedError(
        "predict.py CLI path requires the combiner-input loaders from "
        "future iterations of #30/#31; the library function "
        "produce_forecast() is the testable entry point in #33."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    args = _build_parser().parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set")
        return 2

    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn) as conn:
        try:
            posterior = _load_inputs_from_db(conn)
        except NotImplementedError as exc:
            logger.error("predict: %s", exc)
            return 2
        result = produce_forecast(
            conn,
            posterior=posterior,
            model_version=args.model_version,
            methodology_url=args.methodology_url,
            cycle=args.cycle,
            round_=args.round_,
            run_kind=args.run_kind,
        )
        conn.commit()

    print(f"run_id={result.run_id}")
    return 0


__all__ = [
    "METHODOLOGY_URL",
    "MODEL_VERSION",
    "NOTIFY_CHANNEL",
    "QUANTILE_KEYS",
    "RACE_TYPE_PRESIDENTIAL",
    "ForecastWriteResult",
    "build_presidential_payload",
    "main",
    "posterior_sample_array",
    "produce_forecast",
    "write_forecast",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
