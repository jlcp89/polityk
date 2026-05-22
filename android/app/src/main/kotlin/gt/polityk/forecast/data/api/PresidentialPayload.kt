package gt.polityk.forecast.data.api

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * Canonical `/v1/forecast/presidential` payload per ADR-014.
 *
 * The Go API serves exactly this shape (`forecasts.payload` is the JSONB column).
 * The Android client never recomputes intervals from samples — quantiles are
 * authoritative.
 */
@JsonClass(generateAdapter = true)
data class PresidentialPayload(
    @Json(name = "run_id") val runId: String,
    @Json(name = "model_version") val modelVersion: String,
    @Json(name = "generated_at") val generatedAt: String,
    @Json(name = "race") val race: Race,
    @Json(name = "candidates") val candidates: List<Candidate>,
    @Json(name = "runoff_matrix") val runoffMatrix: List<RunoffPair> = emptyList(),
    @Json(name = "interventions_applied") val interventionsApplied: List<Intervention> = emptyList(),
    @Json(name = "methodology_url") val methodologyUrl: String,
    @Json(name = "cache_invalid_until") val cacheInvalidUntil: String? = null,
)

@JsonClass(generateAdapter = true)
data class Race(
    @Json(name = "type") val type: String,
    @Json(name = "cycle") val cycle: Int,
    @Json(name = "round") val round: Int,
)

@JsonClass(generateAdapter = true)
data class Candidate(
    @Json(name = "candidate_id") val candidateId: Long,
    @Json(name = "name") val name: String,
    @Json(name = "wikidata_qid") val wikidataQid: String? = null,
    @Json(name = "party_id") val partyId: Long,
    @Json(name = "party_name") val partyName: String,
    @Json(name = "vote_share") val voteShare: VoteShareQuantiles,
    @Json(name = "win_probability_round1") val winProbabilityRound1: Double,
    @Json(name = "qualifies_for_runoff_probability") val qualifiesForRunoffProbability: Double,
)

/**
 * Seven quantiles of a candidate's first-round vote share posterior.
 *
 * Range invariant: 0 ≤ p05 ≤ p10 ≤ p25 ≤ p50 ≤ p75 ≤ p90 ≤ p95 ≤ 1.
 * Enforced server-side in calibration gate C4 (ADR-013); client trusts.
 */
@JsonClass(generateAdapter = true)
data class VoteShareQuantiles(
    @Json(name = "p05") val p05: Double,
    @Json(name = "p10") val p10: Double,
    @Json(name = "p25") val p25: Double,
    @Json(name = "p50") val p50: Double,
    @Json(name = "p75") val p75: Double,
    @Json(name = "p90") val p90: Double,
    @Json(name = "p95") val p95: Double,
)

@JsonClass(generateAdapter = true)
data class RunoffPair(
    @Json(name = "candidate_a_id") val candidateAId: Long,
    @Json(name = "candidate_b_id") val candidateBId: Long,
    @Json(name = "pair_probability") val pairProbability: Double,
    @Json(name = "winner_a_probability") val winnerAProbability: Double,
)

@JsonClass(generateAdapter = true)
data class Intervention(
    @Json(name = "kind") val kind: String,
    @Json(name = "target_kind") val targetKind: String,
    @Json(name = "target_id") val targetId: Long,
    @Json(name = "target_name") val targetName: String,
    @Json(name = "reason") val reason: String,
    @Json(name = "effective_at") val effectiveAt: String,
)
