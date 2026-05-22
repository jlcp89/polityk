package gt.polityk.forecast.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class RelativeTimeTest {
    private val base: Instant = Instant.parse("2026-05-22T12:00:00Z")

    private fun clockAt(instant: Instant): Clock = Clock.fixed(instant, ZoneOffset.UTC)

    @Test
    fun `under one hour returns hace unos minutos`() {
        val generated = "2026-05-22T11:30:00Z"
        val now = clockAt(base)
        assertEquals("hace unos minutos", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `exactly one hour returns singular form`() {
        val generated = "2026-05-22T11:00:00Z"
        val now = clockAt(base)
        assertEquals("hace 1 hora", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `six hour bucket returns plural form`() {
        val generated = "2026-05-22T06:00:00Z"
        val now = clockAt(base)
        assertEquals("hace 6 horas", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `twenty-three hour bucket still reports in hours`() {
        val generated = "2026-05-21T13:00:00Z"
        val now = clockAt(base)
        assertEquals("hace 23 horas", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `exactly one day returns singular dia`() {
        val generated = "2026-05-21T12:00:00Z"
        val now = clockAt(base)
        assertEquals("hace 1 día", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `multi-day bucket returns plural dias`() {
        val generated = "2026-05-19T12:00:00Z"
        val now = clockAt(base)
        assertEquals("hace 3 días", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `future timestamps return ahora rather than negative durations`() {
        val generated = "2026-05-22T13:00:00Z"
        val now = clockAt(base)
        assertEquals("ahora", RelativeTime.formatSpanish(generated, now))
    }

    @Test
    fun `unparseable input returns null instead of throwing`() {
        val now = clockAt(base)
        assertNull(RelativeTime.formatSpanish("not-a-timestamp", now))
        assertNull(RelativeTime.formatSpanish("", now))
    }
}
