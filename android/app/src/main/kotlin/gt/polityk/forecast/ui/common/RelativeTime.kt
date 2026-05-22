package gt.polityk.forecast.ui.common

import java.time.Clock
import java.time.Duration
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

/**
 * Pure formatter for the "Actualizado hace X horas" stamp on the
 * presidential and methodology screens.
 *
 * Buckets chosen to match ADR-018 / issue #42 freshness bands so the
 * "fresh" stamp and the future yellow/red banners read consistently:
 *
 *   - < 1 h        → "hace unos minutos"
 *   - 1 h          → "hace 1 hora"
 *   - 2 h ... 23 h → "hace N horas"
 *   - 1 day        → "hace 1 día"
 *   - 2 days ...   → "hace N días"
 *
 * Returns `null` when the input is unparseable so callers can suppress
 * the stamp rather than render a misleading value.
 */
object RelativeTime {
    fun formatSpanish(
        generatedAtIso: String,
        clock: Clock,
    ): String? {
        val instant =
            try {
                OffsetDateTime.parse(generatedAtIso).toInstant()
            } catch (_: DateTimeParseException) {
                return null
            }
        val now = clock.instant()
        val elapsed = Duration.between(instant, now)
        if (elapsed.isNegative) {
            return "ahora"
        }
        val hours = elapsed.toHours()
        return when {
            hours < 1L -> "hace unos minutos"
            hours == 1L -> "hace 1 hora"
            hours < HOURS_PER_DAY -> "hace $hours horas"
            else -> formatDays(elapsed.toDays())
        }
    }

    private fun formatDays(days: Long): String =
        when (days) {
            1L -> "hace 1 día"
            else -> "hace $days días"
        }

    private const val HOURS_PER_DAY = 24L
}
