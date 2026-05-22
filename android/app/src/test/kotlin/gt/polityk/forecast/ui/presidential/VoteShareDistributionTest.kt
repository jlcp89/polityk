package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.VoteShareQuantiles
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VoteShareDistributionTest {
    @Test
    fun `density curve has a point per midpoint plus two tail endpoints`() {
        val q = VoteShareQuantiles(0.10, 0.12, 0.16, 0.20, 0.24, 0.28, 0.30)
        val curve = quantilesToDensityPoints(q)
        // 7 quantiles -> 6 midpoint segments + 2 tail caps = 8 points
        assertEquals(8, curve.size)
        assertEquals(0.10, curve.first().x, 1e-9)
        assertEquals(0.30, curve.last().x, 1e-9)
    }

    @Test
    fun `peak density sits near the median when distribution is symmetric`() {
        // symmetric around 0.20, with the narrowest interquartile width near the centre
        val q = VoteShareQuantiles(0.10, 0.12, 0.18, 0.20, 0.22, 0.28, 0.30)
        val curve = quantilesToDensityPoints(q)
        val peak = curve.maxBy { it.density }
        // peak x should be within ±5pp of the median
        assertTrue("peak ${peak.x} should be near median 0.20", kotlin.math.abs(peak.x - 0.20) <= 0.05)
    }

    @Test
    fun `zero-width segment produces zero density rather than NaN or Infinity`() {
        // p05 == p10 (candidate floored near 0%)
        val q = VoteShareQuantiles(0.00, 0.00, 0.02, 0.05, 0.08, 0.12, 0.15)
        val curve = quantilesToDensityPoints(q)
        curve.forEach { p ->
            assertTrue("density must be finite: ${p.density}", p.density.isFinite())
            assertTrue("density must be >= 0: ${p.density}", p.density >= 0.0)
        }
    }

    @Test
    fun `out-of-range quantile yields empty curve so renderer can skip drawing`() {
        val q = VoteShareQuantiles(-0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 1.5)
        val curve = quantilesToDensityPoints(q)
        assertEquals(0, curve.size)
    }

    @Test
    fun `formatPercent renders one decimal`() {
        assertEquals("23.0%", formatPercent(0.23))
        assertEquals("4.0%", formatPercent(0.04))
        assertEquals("0.5%", formatPercent(0.005))
    }

    @Test
    fun `every fixture candidate produces a non-empty density curve`() {
        val payload = gt.polityk.forecast.test.Fixtures.fivePresidentialCandidates()
        payload.candidates.forEach { c ->
            val curve = quantilesToDensityPoints(c.voteShare)
            assertNotNull(curve)
            assertTrue("${c.name} has non-empty density curve", curve.isNotEmpty())
        }
    }
}
