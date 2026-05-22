package gt.polityk.forecast.ui.blackout

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class BlackoutResumeCalculatorTest {
    // GT = UTC-6, no DST. 18:00 GT == 00:00 UTC next day.

    @Test
    fun `Friday afternoon mid-blackout resolves to next Sunday 18 GT`() {
        // 2026-06-26 Fri 19:00 GT == 2026-06-27T01:00:00Z
        val clock = Clock.fixed(Instant.parse("2026-06-27T01:00:00Z"), ZoneOffset.UTC)
        // 2026-06-28 Sun 18:00 GT
        val expected = Instant.parse("2026-06-29T00:00:00Z")
        assertEquals(expected, BlackoutResumeCalculator.nextResumeInstant(clock))
    }

    @Test
    fun `Sunday before 18 GT resolves to today 18 GT`() {
        // 2026-06-28 Sun 12:00 GT == 2026-06-28T18:00:00Z
        val clock = Clock.fixed(Instant.parse("2026-06-28T18:00:00Z"), ZoneOffset.UTC)
        assertEquals(
            Instant.parse("2026-06-29T00:00:00Z"),
            BlackoutResumeCalculator.nextResumeInstant(clock),
        )
    }

    @Test
    fun `Sunday at exactly 18 GT advances to the following Sunday`() {
        // 2026-06-28 Sun 18:00 GT == 2026-06-29T00:00:00Z
        val clock = Clock.fixed(Instant.parse("2026-06-29T00:00:00Z"), ZoneOffset.UTC)
        // 2026-07-05 Sun 18:00 GT
        val expected = Instant.parse("2026-07-06T00:00:00Z")
        assertEquals(expected, BlackoutResumeCalculator.nextResumeInstant(clock))
    }

    @Test
    fun `mid-week Wednesday resolves to upcoming Sunday 18 GT`() {
        // 2026-06-24 Wed 10:00 GT == 2026-06-24T16:00:00Z
        val clock = Clock.fixed(Instant.parse("2026-06-24T16:00:00Z"), ZoneOffset.UTC)
        assertEquals(
            Instant.parse("2026-06-29T00:00:00Z"),
            BlackoutResumeCalculator.nextResumeInstant(clock),
        )
    }

    @Test
    fun `Saturday morning resolves to the following day at 18 GT`() {
        // 2026-06-27 Sat 08:00 GT == 2026-06-27T14:00:00Z
        val clock = Clock.fixed(Instant.parse("2026-06-27T14:00:00Z"), ZoneOffset.UTC)
        assertEquals(
            Instant.parse("2026-06-29T00:00:00Z"),
            BlackoutResumeCalculator.nextResumeInstant(clock),
        )
    }
}
