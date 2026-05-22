package gt.polityk.forecast.ui.blackout

import java.time.Clock
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId
import java.time.temporal.TemporalAdjusters

/**
 * Computes when the forecast resumes after a legal blackout (expediente
 * 1699-2018). Heuristic per ADR-014 / ADR-003: the next Sunday at 18:00
 * America/Guatemala (UTC-6, no DST).
 *
 * Pure function — takes a [Clock] so the splash composable can be unit-
 * tested across weekend / mid-week / mid-blackout cases without touching
 * the wall clock.
 */
object BlackoutResumeCalculator {
    val GUATEMALA_ZONE: ZoneId = ZoneId.of("America/Guatemala")
    val RESUME_LOCAL_TIME: LocalTime = LocalTime.of(18, 0)

    fun nextResumeInstant(clock: Clock): Instant {
        val now = Instant.now(clock).atZone(GUATEMALA_ZONE)
        val todayAtResume = now.toLocalDate().atTime(RESUME_LOCAL_TIME).atZone(GUATEMALA_ZONE)
        val candidate =
            if (now.dayOfWeek == DayOfWeek.SUNDAY && now.isBefore(todayAtResume)) {
                todayAtResume
            } else {
                now.with(TemporalAdjusters.next(DayOfWeek.SUNDAY))
                    .toLocalDate()
                    .atTime(RESUME_LOCAL_TIME)
                    .atZone(GUATEMALA_ZONE)
            }
        return candidate.toInstant()
    }
}
