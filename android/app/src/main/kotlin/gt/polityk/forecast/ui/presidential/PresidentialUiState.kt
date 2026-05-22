package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.PresidentialPayload

/**
 * Graduated freshness banners per ADR-018. Buckets:
 *
 * - [Fresh]         payload generated ≤ 6h ago — render normally, no banner
 * - [SlightlyStale] 6h <  age ≤ 24h          — yellow banner above the payload
 * - [Stale]         24h <  age ≤ 72h          — red banner + prominent retry
 * - [NoRecentData]  age > 72h OR `cache_invalid_until` in the past — forecast suppressed
 *
 * [Loading] and [Error] are orthogonal to the freshness buckets and represent
 * "no cached or fresh payload yet known".
 */
sealed interface PresidentialUiState {
    data object Loading : PresidentialUiState

    sealed interface Loaded : PresidentialUiState {
        val payload: PresidentialPayload
        val ageHours: Long
    }

    data class Fresh(
        override val payload: PresidentialPayload,
        override val ageHours: Long,
    ) : Loaded

    data class SlightlyStale(
        override val payload: PresidentialPayload,
        override val ageHours: Long,
    ) : Loaded

    data class Stale(
        override val payload: PresidentialPayload,
        override val ageHours: Long,
    ) : Loaded

    data object NoRecentData : PresidentialUiState

    data class Error(val message: String) : PresidentialUiState
}
