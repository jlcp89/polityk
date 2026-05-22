package gt.polityk.forecast.data.repo

import com.squareup.moshi.JsonAdapter
import gt.polityk.forecast.data.api.BlackoutException
import gt.polityk.forecast.data.api.PolitykApi
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.db.ForecastCacheDao
import gt.polityk.forecast.data.db.ForecastCacheEntity
import java.time.Clock
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Fetches the presidential forecast, writes the raw payload into the Room
 * cache for later freshness checks (issue #42), and on a Blackout response
 * (HTTP 503, surfaced as [BlackoutException] by the interceptor) wipes the
 * cached payload for this endpoint and rethrows so the ViewModel can emit
 * the Blackout splash state.
 */
@Singleton
class PresidentialRepository
    @Inject
    constructor(
        private val api: PolitykApi,
        private val cacheDao: ForecastCacheDao,
        private val payloadAdapter: JsonAdapter<PresidentialPayload>,
        private val clock: Clock,
    ) {
        suspend fun fetch(): PresidentialPayload {
            val payload =
                try {
                    api.getPresidential()
                } catch (blackout: BlackoutException) {
                    runCatching { cacheDao.deleteByEndpoint(PRESIDENTIAL_ENDPOINT_KEY) }
                    throw blackout
                }
            runCatching {
                cacheDao.upsert(
                    ForecastCacheEntity(
                        endpointUrl = PRESIDENTIAL_ENDPOINT_KEY,
                        payloadJson = payloadAdapter.toJson(payload),
                        generatedAtEpochMs = parseIsoToEpochMs(payload.generatedAt),
                        cacheInvalidUntilEpochMs = payload.cacheInvalidUntil?.let(::parseIsoToEpochMs),
                        fetchedAtEpochMs = clock.millis(),
                    ),
                )
            }
            return payload
        }

        /**
         * Read the cached entry for the presidential endpoint, honouring
         * `cache_invalid_until` as a forced expiry per issue #43 AC. A row
         * whose `cacheInvalidUntilEpochMs <= now` is treated as missing
         * (returns `null`) and the caller must force a fresh fetch. Rows
         * with a null `cacheInvalidUntilEpochMs` are never forced-expired
         * by this helper — the freshness banner state machine in #42
         * applies its own age buckets.
         */
        suspend fun readCacheIfValid(): ForecastCacheEntity? {
            val entry = cacheDao.get(PRESIDENTIAL_ENDPOINT_KEY) ?: return null
            val invalidUntil = entry.cacheInvalidUntilEpochMs ?: return entry
            return if (invalidUntil <= clock.millis()) null else entry
        }

        private fun parseIsoToEpochMs(iso: String): Long? =
            try {
                OffsetDateTime.parse(iso).toInstant().toEpochMilli()
            } catch (_: DateTimeParseException) {
                null
            }

        companion object {
            const val PRESIDENTIAL_ENDPOINT_KEY: String = "/v1/forecast/presidential"
        }
    }
