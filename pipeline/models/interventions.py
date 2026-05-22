"""Intervention applier — transforms presidential posteriors per ADR-019.

Implements issue #35. Reads "active at now()" rows from the ``interventions``
table written by :mod:`pipeline.scripts.intervene` (#34), then transforms the
presidential posterior produced by the combiner (#32, :mod:`pipeline.models.
presidential`) **before** the forecast writer (#33, :mod:`pipeline.scripts.
predict`) builds the ADR-014 payload.

Two transformation kinds per ADR-019:

* ``disqualified`` / ``withdrew`` / ``party_cancelled``
    Zero the target's column in every posterior sample, then renormalise the
    row to sum to 1.0. Mass that previously sat on the disqualified target is
    redistributed proportionally across the surviving candidates.

* ``manual_probability``
    Replace the target's marginal with a delta at ``override_probability``
    (per-row) and rescale the sibling columns proportionally to sum to
    ``1 - override_probability``. The override is the candidate's posterior
    probability *for that row*, not the candidate's total mass across the
    field.

Targets are resolved as follows:

* ``target_kind='candidate'`` → the single column whose ``candidate_id``
  matches ``target_id``.
* ``target_kind='party'``     → every column whose ``party_id`` matches
  ``target_id`` (treated as one block for ``manual_probability``).
* ``target_kind='race'``      → no per-candidate action in the presidential
  applier; the row is still surfaced in ``interventions_applied`` for the
  audit trail.

The applier also returns the payload-shaped ``interventions_applied`` list
required by ADR-014:

    [{"kind", "target_kind", "target_id", "target_name", "reason",
      "effective_at"}]

where ``target_name`` is resolved at load time by left-joining ``candidates``
or ``parties``. Race-level targets carry ``target_name = None``.

The runoff matrix is rebuilt deterministically from the modified samples:
pair probabilities come from counting new top-two pairs, and the
``winner_a_probability`` is inherited from the original runoff matrix when
the (a, b) pair already appeared there. New pairs (introduced because a
finalist was just disqualified) inherit the next-best information available:
the modal pair's ``winner_a_probability``, or 0.5 when the original matrix
is empty. This is an approximation — re-running the runoff swing model is
out of scope here — but it keeps disqualified candidates from re-appearing
in the matrix and preserves ADR-013 C5 (``pair_probability`` sums to 1.0).

The DB query is parameter-safe, returns the rows ordered by
``intervention_id`` for deterministic application, and is the only piece of
this module that depends on psycopg.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pipeline.models.presidential import (
    CandidateInput,
    PresidentialPosterior,
    RunoffMatrixEntry,
    _build_runoff_matrix,
    _per_candidate_summary,
)

# Kinds that zero out the target column and renormalise the rest.
_ZERO_KINDS: frozenset[str] = frozenset(
    {"disqualified", "withdrew", "party_cancelled"}
)
_MANUAL_KIND: str = "manual_probability"

# Numerical tolerance for "row sums to 1" guards.
_ROW_SUM_EPS: float = 1e-12


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Intervention:
    """One row from the ``interventions`` table with the target name resolved.

    ``target_name`` is left-joined at load time so the payload writer doesn't
    need a second DB round-trip per intervention; it is ``None`` when the
    target row no longer exists or for ``target_kind='race'``.
    """

    intervention_id: int
    target_kind: str
    target_id: int
    kind: str
    effective_at: datetime
    expires_at: datetime | None
    override_probability: float | None
    reason: str
    operator: str
    target_name: str | None = None


# ---------------------------------------------------------------------------
# DB loader
# ---------------------------------------------------------------------------


_LOAD_SQL: str = """
SELECT
    i.intervention_id,
    i.target_kind::text,
    i.target_id,
    i.kind::text,
    i.effective_at,
    i.expires_at,
    i.override_probability,
    i.reason,
    i.operator,
    CASE
        WHEN i.target_kind = 'candidate' THEN
            (SELECT full_name FROM candidates c WHERE c.candidate_id = i.target_id)
        WHEN i.target_kind = 'party' THEN
            (SELECT name FROM parties p WHERE p.party_id = i.target_id)
        ELSE NULL
    END AS target_name
FROM interventions i
WHERE i.effective_at <= %s
  AND (i.expires_at IS NULL OR i.expires_at > %s)
ORDER BY i.intervention_id
"""


def load_active_interventions(
    conn: Any,
    *,
    at: datetime | None = None,
) -> list[Intervention]:
    """Read ``interventions`` active at ``at`` (defaults to ``now()``).

    Returns rows ordered by ``intervention_id`` so the applier is fully
    deterministic. ``at`` must be timezone-aware when supplied — the
    interventions table is ``TIMESTAMPTZ``, so a naive timestamp is a bug.
    """
    when = at if at is not None else datetime.now(UTC)
    if when.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")

    with conn.cursor() as cur:
        cur.execute(_LOAD_SQL, (when, when))
        rows = cur.fetchall()

    interventions: list[Intervention] = []
    for row in rows:
        (
            intervention_id,
            target_kind,
            target_id,
            kind,
            effective_at,
            expires_at,
            override_probability,
            reason,
            operator,
            target_name,
        ) = row
        interventions.append(
            Intervention(
                intervention_id=int(intervention_id),
                target_kind=str(target_kind),
                target_id=int(target_id),
                kind=str(kind),
                effective_at=effective_at,
                expires_at=expires_at,
                override_probability=(
                    float(override_probability)
                    if override_probability is not None
                    else None
                ),
                reason=str(reason),
                operator=str(operator),
                target_name=str(target_name) if target_name is not None else None,
            )
        )
    return interventions


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _affected_columns(
    intervention: Intervention,
    candidate_inputs: Sequence[CandidateInput],
) -> list[int]:
    """Return the column indices touched by ``intervention``.

    Race-level targets never touch a column directly; they still appear in
    ``interventions_applied`` so analysts can see the row.
    """
    if intervention.target_kind == "candidate":
        return [
            j
            for j, ci in enumerate(candidate_inputs)
            if ci.candidate_id == intervention.target_id
        ]
    if intervention.target_kind == "party":
        return [
            j
            for j, ci in enumerate(candidate_inputs)
            if ci.party_id is not None and ci.party_id == intervention.target_id
        ]
    return []


# ---------------------------------------------------------------------------
# Pure-math sample transformer
# ---------------------------------------------------------------------------


def apply_interventions_to_samples(
    samples: Any,
    candidate_inputs: Sequence[CandidateInput],
    interventions: Sequence[Intervention],
) -> Any:
    """Transform an ``(n_mc, n_candidates)`` share matrix per ``interventions``.

    The input is first normalised row-wise to sum to 1.0 so the per-kind
    transformations have a stable contract; the returned matrix also has
    rows that sum to 1.0 ± :data:`_ROW_SUM_EPS`. The original ``samples``
    array is not mutated.

    Empty ``interventions`` returns a copy normalised to sum-to-1; this is
    documented intentional behaviour — the applier always returns a clean
    probability distribution.
    """
    import numpy as np  # noqa: PLC0415

    s = np.asarray(samples, dtype=float).copy()
    if s.ndim != 2:
        raise ValueError(f"samples must be 2-D, got shape {s.shape}")
    s = _renormalise_rows(s)

    for itv in interventions:
        cols = _affected_columns(itv, candidate_inputs)
        if not cols:
            # Race-level or unmatched target: no per-sample math.
            continue

        if itv.kind in _ZERO_KINDS:
            s[:, cols] = 0.0
            s = _renormalise_rows(s)
            continue

        if itv.kind == _MANUAL_KIND:
            if itv.override_probability is None:
                raise ValueError(
                    f"intervention_id={itv.intervention_id}: "
                    f"manual_probability requires override_probability"
                )
            s = _apply_manual_probability(
                s, cols=cols, override=float(itv.override_probability)
            )
            continue

        # Unknown kinds: surface loudly rather than silently skip.
        raise ValueError(
            f"intervention_id={itv.intervention_id}: unknown kind {itv.kind!r}"
        )

    return s


def _renormalise_rows(s: Any) -> Any:
    """Divide each row by its sum; rows that already sum to 0 stay 0.

    Returns a fresh array. Rows with zero total are an edge case (every
    candidate's marginal got rounded to zero or every column was disqualified)
    — we leave them at zero so callers can detect the pathology rather than
    masking it with a fabricated uniform distribution.
    """
    import numpy as np  # noqa: PLC0415

    row_sums = s.sum(axis=1, keepdims=True)
    safe = np.where(row_sums > _ROW_SUM_EPS, row_sums, 1.0)
    out = s / safe
    # Restore zero rows where the original sum was zero — division-by-1 above
    # would have left the original (zero) values intact, which is correct.
    return out


def _apply_manual_probability(
    s: Any,
    *,
    cols: list[int],
    override: float,
) -> Any:
    """Set columns ``cols`` to ``override`` (split proportionally for parties)
    and rescale every other column to fill ``1 - override`` per row.

    Per-row recipe:

    * If the target was a single candidate column, that column's row value
      becomes ``override``.
    * If the target spans multiple columns (party intervention), the
      ``override`` is split across the affected columns proportionally to
      their pre-intervention shares; if those shares all rounded to zero,
      the split is uniform.
    * Sibling columns are scaled by ``(1 - override) / sum(siblings)``.
      Rows where every sibling is zero get all their mass on the target.
    """
    import numpy as np  # noqa: PLC0415

    if not 0.0 <= override <= 1.0:
        raise ValueError(f"override_probability must be in [0,1], got {override}")
    if not cols:
        return s

    out = s.copy()
    target_block = out[:, cols]  # (n_mc, k)
    target_row_sum = target_block.sum(axis=1, keepdims=True)
    n_targets = len(cols)
    equal = np.full_like(target_block, 1.0 / n_targets)
    target_share = np.where(
        target_row_sum > _ROW_SUM_EPS,
        target_block / np.where(target_row_sum > _ROW_SUM_EPS, target_row_sum, 1.0),
        equal,
    )
    out[:, cols] = override * target_share

    sibling_mask = np.ones(out.shape[1], dtype=bool)
    sibling_mask[cols] = False
    sibling_total = out[:, sibling_mask].sum(axis=1, keepdims=True)
    # `(1 - override)` is the budget for siblings. When override == 1.0 the
    # siblings all collapse to zero; when override == 0.0 the target ends up
    # at zero and siblings are renormalised to sum to 1.0.
    sibling_budget = 1.0 - override
    scale = np.where(
        sibling_total > _ROW_SUM_EPS,
        sibling_budget / np.where(sibling_total > _ROW_SUM_EPS, sibling_total, 1.0),
        0.0,
    )
    out[:, sibling_mask] = out[:, sibling_mask] * scale
    return out


# ---------------------------------------------------------------------------
# Payload-shaped metadata
# ---------------------------------------------------------------------------


def serialize_interventions_applied(
    interventions: Sequence[Intervention],
) -> list[dict[str, Any]]:
    """Build the payload's ``interventions_applied`` array per ADR-014.

    Order matches the loader: rows ordered by ``intervention_id``. Empty
    ``interventions`` returns an empty list (the ADR-014 default).
    """
    out: list[dict[str, Any]] = []
    for itv in interventions:
        out.append(
            {
                "kind": itv.kind,
                "target_kind": itv.target_kind,
                "target_id": itv.target_id,
                "target_name": itv.target_name,
                "reason": itv.reason,
                "effective_at": _format_iso8601_utc(itv.effective_at),
            }
        )
    return out


def _format_iso8601_utc(dt: datetime) -> str:
    """Match the format produced by :mod:`pipeline.scripts.predict`."""
    if dt.tzinfo is None:
        raise ValueError("effective_at must be timezone-aware")
    return dt.astimezone(UTC).isoformat()


# ---------------------------------------------------------------------------
# Posterior-level applier
# ---------------------------------------------------------------------------


def apply_interventions(
    posterior: PresidentialPosterior,
    interventions: Sequence[Intervention],
) -> tuple[PresidentialPosterior, list[dict[str, Any]]]:
    """Transform ``posterior``; return (modified, interventions_applied).

    Empty ``interventions`` is a pure pass-through (the original ``posterior``
    object is returned, and the metadata list is empty) so this function is
    cheap on the common no-intervention path.
    """
    if not interventions:
        return posterior, []

    candidate_inputs = _candidate_inputs_from_posterior(posterior)
    new_samples = apply_interventions_to_samples(
        posterior.first_round_samples, candidate_inputs, interventions
    )

    import numpy as np  # noqa: PLC0415

    order = np.argsort(new_samples, axis=1)
    top1_idx = order[:, -1]
    top2_idx = order[:, -2]

    candidates = _per_candidate_summary(
        candidate_inputs=candidate_inputs,
        first_round_samples=new_samples,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
    )

    win_a_lookup = _winner_a_probability_lookup(posterior.runoff_matrix)
    fallback_win_a = _fallback_winner_a_probability(posterior.runoff_matrix)
    cand_ids = [ci.candidate_id for ci in candidate_inputs]
    win_a_prob = np.array(
        [
            win_a_lookup.get(
                (cand_ids[int(top1_idx[s])], cand_ids[int(top2_idx[s])]),
                fallback_win_a,
            )
            for s in range(top1_idx.shape[0])
        ],
        dtype=float,
    )

    runoff_matrix = _build_runoff_matrix(
        candidate_inputs=candidate_inputs,
        top1_idx=top1_idx,
        top2_idx=top2_idx,
        win_a_prob=win_a_prob,
    )

    new_posterior = dataclasses.replace(
        posterior,
        candidates=candidates,
        runoff_matrix=runoff_matrix,
        first_round_samples=new_samples,
        n_monte_carlo=int(new_samples.shape[0]),
    )
    return new_posterior, serialize_interventions_applied(interventions)


def _candidate_inputs_from_posterior(
    posterior: PresidentialPosterior,
) -> list[CandidateInput]:
    """Reconstruct ``CandidateInput`` rows from the posterior's candidate list.

    The combiner stores candidate identity on each :class:`CandidatePosterior`;
    the applier rebuilds the (column-ordered) :class:`CandidateInput` list so
    the helpers that ship with :mod:`pipeline.models.presidential` can be
    reused verbatim.
    """
    return [
        CandidateInput(
            candidate_id=cp.candidate_id,
            name=cp.name,
            party_id=cp.party_id,
            party_name=cp.party_name,
            wikidata_qid=cp.wikidata_qid,
            feature_vector=None,
        )
        for cp in posterior.candidates
    ]


def _winner_a_probability_lookup(
    runoff_matrix: Sequence[RunoffMatrixEntry],
) -> dict[tuple[int, int], float]:
    """``(a_id, b_id) -> winner_a_probability`` lookup for matrix reuse."""
    return {
        (e.a_candidate_id, e.b_candidate_id): float(e.winner_a_probability)
        for e in runoff_matrix
    }


def _fallback_winner_a_probability(
    runoff_matrix: Sequence[RunoffMatrixEntry],
) -> float:
    """Default ``winner_a_probability`` for previously-unseen (a, b) pairs.

    Picks the most-likely entry from the original matrix when one exists —
    its swing-model-informed probability is a better default than 0.5 for
    similar share gaps. Falls back to 0.5 when the original matrix is empty
    (no historical signal is available).
    """
    if not runoff_matrix:
        return 0.5
    best = max(runoff_matrix, key=lambda e: e.pair_probability)
    return float(best.winner_a_probability)


__all__ = [
    "Intervention",
    "apply_interventions",
    "apply_interventions_to_samples",
    "load_active_interventions",
    "serialize_interventions_applied",
]
