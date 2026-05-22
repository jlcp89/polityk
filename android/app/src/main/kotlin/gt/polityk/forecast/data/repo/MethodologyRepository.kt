package gt.polityk.forecast.data.repo

import gt.polityk.forecast.data.api.MethodologyPayload
import gt.polityk.forecast.data.api.PolitykApi
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Fetches `/v1/methodology`. The endpoint is never gated by the blackout
 * middleware so this repository has no Room caching layer — a fresh fetch
 * per screen open is cheap (small response, `Cache-Control: public,
 * max-age=3600`) and avoids stale model-version mismatches with the
 * presidential payload's `methodology_url`.
 */
@Singleton
class MethodologyRepository
    @Inject
    constructor(
        private val api: PolitykApi,
    ) {
        suspend fun fetch(): MethodologyPayload = api.getMethodology()
    }
