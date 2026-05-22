package gt.polityk.forecast.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * One row per endpoint URL — keyed exactly as ADR-018 requires.
 *
 * `payloadJson` stores the raw API response body unchanged so the freshness
 * banner logic in issue #42 can re-parse without a re-fetch. `generatedAt`
 * and `cacheInvalidUntil` are extracted from the payload for cheap freshness
 * checks; both are ISO-8601 epoch-millis-since-Unix values, NULL if absent.
 */
@Entity(tableName = "forecast_cache")
data class ForecastCacheEntity(
    @PrimaryKey val endpointUrl: String,
    val payloadJson: String,
    val generatedAtEpochMs: Long?,
    val cacheInvalidUntilEpochMs: Long?,
    val fetchedAtEpochMs: Long,
)
