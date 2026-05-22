package gt.polityk.forecast.data.repo

import com.squareup.moshi.JsonAdapter
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
 * Fetches the presidential forecast and writes the raw payload into the Room
 * cache for later freshness checks (issue #42). This issue scaffolds cache
 * **writes only** — there is no read-through here. Tests assert the write side.
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
            val payload = api.getPresidential()
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
