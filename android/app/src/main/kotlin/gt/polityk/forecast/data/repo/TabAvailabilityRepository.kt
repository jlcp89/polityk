package gt.polityk.forecast.data.repo

import android.content.SharedPreferences
import androidx.core.content.edit
import gt.polityk.forecast.data.api.PolitykApi
import okhttp3.ResponseBody
import retrofit2.Response
import java.io.IOException
import java.time.Clock
import java.time.Duration
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Probes `/v1/forecast/congress` and `/v1/forecast/municipal/0` on a 24-hour
 * cadence (per issue #44) to decide whether the congress and municipal tabs
 * should appear in the bottom navigation. 200 → tab visible; 404 → hidden.
 *
 * Caches the decision in [SharedPreferences] so we don't pay two network
 * round-trips on every cold start. Network errors (timeouts, DNS failures,
 * 5xx) intentionally do NOT poison the cache — defaulting to "show" is the
 * less surprising failure mode (the user can at least open the tab and see
 * the error screen) and re-probing on the next cold start is cheap.
 */
@Singleton
class TabAvailabilityRepository
    @Inject
    constructor(
        private val api: PolitykApi,
        private val prefs: SharedPreferences,
        private val clock: Clock,
    ) {
        /**
         * Returns the cached availability if it is still within the 24h TTL;
         * otherwise re-probes both endpoints and writes the result back.
         */
        suspend fun availability(forceRefresh: Boolean = false): TabAvailability {
            if (!forceRefresh) {
                readCached()?.let { return it }
            }
            val congress = probe { api.probeCongress() }
            val municipal = probe { api.probeMunicipal(MUNICIPAL_SENTINEL_ID) }
            // Only cache when both probes returned a definitive HTTP status code.
            // If either ended in a network exception, leave the cache untouched
            // so the next cold start retries instead of locking in a transient
            // result for 24h.
            val cacheable = congress != null && municipal != null
            val result =
                TabAvailability(
                    congressAvailable = congress ?: true,
                    municipalAvailable = municipal ?: true,
                )
            if (cacheable) {
                writeCache(result)
            }
            return result
        }

        private suspend fun probe(call: suspend () -> Response<ResponseBody>): Boolean? =
            try {
                val response = call()
                response.body()?.close()
                response.errorBody()?.close()
                when (response.code()) {
                    HTTP_NOT_FOUND -> false
                    in HTTP_OK_RANGE -> true
                    else -> null
                }
            } catch (_: IOException) {
                null
            }

        private fun readCached(): TabAvailability? {
            if (!prefs.contains(KEY_CONGRESS) || !prefs.contains(KEY_MUNICIPAL)) return null
            val writtenAt = prefs.getLong(KEY_WRITTEN_AT_MS, 0L)
            if (writtenAt == 0L) return null
            val age = Duration.ofMillis(clock.millis() - writtenAt)
            if (age >= TTL || age.isNegative) return null
            return TabAvailability(
                congressAvailable = prefs.getBoolean(KEY_CONGRESS, true),
                municipalAvailable = prefs.getBoolean(KEY_MUNICIPAL, true),
            )
        }

        private fun writeCache(value: TabAvailability) {
            prefs.edit {
                putBoolean(KEY_CONGRESS, value.congressAvailable)
                putBoolean(KEY_MUNICIPAL, value.municipalAvailable)
                putLong(KEY_WRITTEN_AT_MS, clock.millis())
            }
        }

        companion object {
            const val MUNICIPAL_SENTINEL_ID: Long = 0L

            internal const val KEY_CONGRESS = "tab_availability.congress"
            internal const val KEY_MUNICIPAL = "tab_availability.municipal"
            internal const val KEY_WRITTEN_AT_MS = "tab_availability.written_at_ms"

            internal val TTL: Duration = Duration.ofHours(24)

            private const val HTTP_NOT_FOUND = 404
            private val HTTP_OK_RANGE = 200..299
        }
    }
