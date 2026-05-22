package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.PresidentialPayload

private const val MS_PER_HOUR: Long = 60L * 60L * 1000L
internal const val FRESH_HOURS: Long = 6
internal const val SLIGHTLY_STALE_HOURS: Long = 24
internal const val STALE_HOURS: Long = 72

/**
 * Map a payload + its cache metadata into the ADR-018 freshness bucket.
 *
 * Rules (in order):
 *   1. `cacheInvalidUntilMs` non-null and ≤ nowMs           → [PresidentialUiState.NoRecentData]
 *   2. `generatedAtMs` is null (unparseable timestamp)      → [PresidentialUiState.NoRecentData]
 *   3. age (clamped at 0 — generated_at in the future is treated as 0h-old):
 *        - ≤ 6h               → [PresidentialUiState.Fresh]
 *        - 6h <  age ≤ 24h    → [PresidentialUiState.SlightlyStale]
 *        - 24h <  age ≤ 72h   → [PresidentialUiState.Stale]
 *        - > 72h              → [PresidentialUiState.NoRecentData]
 *
 * Pure function — no clocks, no DAO. Trivially unit-testable.
 */
fun bucketize(
    payload: PresidentialPayload,
    generatedAtMs: Long?,
    cacheInvalidUntilMs: Long?,
    nowMs: Long,
): PresidentialUiState {
    if (cacheInvalidUntilMs != null && cacheInvalidUntilMs <= nowMs) {
        return PresidentialUiState.NoRecentData
    }
    val generated = generatedAtMs ?: return PresidentialUiState.NoRecentData
    val ageMs = (nowMs - generated).coerceAtLeast(0L)
    val ageHours = ageMs / MS_PER_HOUR
    return when {
        ageHours <= FRESH_HOURS -> PresidentialUiState.Fresh(payload, ageHours)
        ageHours <= SLIGHTLY_STALE_HOURS -> PresidentialUiState.SlightlyStale(payload, ageHours)
        ageHours <= STALE_HOURS -> PresidentialUiState.Stale(payload, ageHours)
        else -> PresidentialUiState.NoRecentData
    }
}
