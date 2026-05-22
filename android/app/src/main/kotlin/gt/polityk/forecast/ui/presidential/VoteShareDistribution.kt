package gt.polityk.forecast.ui.presidential

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import gt.polityk.forecast.data.api.VoteShareQuantiles
import kotlin.math.max
import kotlin.math.min

private val QUANTILE_PROBS = doubleArrayOf(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

/**
 * A point on the piecewise-linear density curve estimated from quantiles.
 *
 * @property x  vote share in [0, 1]
 * @property density  unnormalised density estimate; the curve is rendered
 *                    relative to its own peak so absolute magnitude doesn't matter.
 */
data class DensityPoint(val x: Double, val density: Double)

/**
 * Estimate a coarse density curve from seven canonical quantiles.
 *
 * Between adjacent quantile points (q_i, q_{i+1}) the local density is
 *
 *     density ≈ (P_{i+1} - P_i) / (q_{i+1} - q_i)
 *
 * — the slope of the empirical CDF. We attribute that local density to the
 * midpoint of each segment, then prepend p05 and append p95 with the boundary
 * densities so the violin tapers cleanly at the tails.
 *
 * Zero-width segments (e.g., a candidate stuck near 0% where p05 == p10) get
 * a density of 0 so the violin doesn't blow up to infinity.
 */
fun quantilesToDensityPoints(q: VoteShareQuantiles): List<DensityPoint> {
    val values = doubleArrayOf(q.p05, q.p10, q.p25, q.p50, q.p75, q.p90, q.p95)
    if (values.any { it.isNaN() } || values.any { it < 0.0 } || values.any { it > 1.0 }) {
        return emptyList()
    }
    // segment densities at midpoints
    val midpoints = ArrayList<DensityPoint>(values.size - 1)
    for (i in 0 until values.size - 1) {
        val width = values[i + 1] - values[i]
        val probMass = QUANTILE_PROBS[i + 1] - QUANTILE_PROBS[i]
        val density = if (width > 1e-9) probMass / width else 0.0
        val mid = (values[i] + values[i + 1]) / 2.0
        midpoints += DensityPoint(mid, density)
    }
    // pin the tails so the violin closes cleanly at p05 / p95
    val first = midpoints.first().density / 2.0
    val last = midpoints.last().density / 2.0
    return buildList(capacity = midpoints.size + 2) {
        add(DensityPoint(values.first(), first))
        addAll(midpoints)
        add(DensityPoint(values.last(), last))
    }
}

@Composable
fun VoteShareDistribution(
    quantiles: VoteShareQuantiles,
    modifier: Modifier = Modifier,
    accent: Color = MaterialTheme.colorScheme.primary,
    soft: Color = MaterialTheme.colorScheme.primaryContainer,
    ink: Color = MaterialTheme.colorScheme.onSurface,
    line: Color = MaterialTheme.colorScheme.outline,
    domainMax: Double = 0.5,
) {
    val density = quantilesToDensityPoints(quantiles)
    val effectiveDomainMax = max(domainMax, quantiles.p95 * 1.05)
    val peakDensity = density.maxOfOrNull { it.density }?.takeIf { it > 0.0 } ?: 1.0

    Column(modifier = modifier) {
        // Violin
        Canvas(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(72.dp)
                    .testTag(VIOLIN_TEST_TAG)
                    .semantics { contentDescription = "Distribución de la intención de voto" },
        ) {
            val w = size.width
            val h = size.height
            val cy = h / 2f

            fun xPx(value: Double): Float = (value / effectiveDomainMax).toFloat().coerceIn(0f, 1f) * w

            fun halfHeightPx(d: Double): Float = ((d / peakDensity).coerceIn(0.0, 1.0) * (h / 2.0)).toFloat()

            if (density.size >= 2) {
                val path =
                    Path().apply {
                        val first = density.first()
                        moveTo(xPx(first.x), cy - halfHeightPx(first.density))
                        for (i in 1 until density.size) {
                            val p = density[i]
                            lineTo(xPx(p.x), cy - halfHeightPx(p.density))
                        }
                        for (i in density.indices.reversed()) {
                            val p = density[i]
                            lineTo(xPx(p.x), cy + halfHeightPx(p.density))
                        }
                        close()
                    }
                drawPath(path = path, color = soft)
                drawPath(path = path, color = accent, style = Stroke(width = 1.5f))
            }

            // Median tick
            val medianX = xPx(quantiles.p50)
            drawLine(
                color = ink,
                start = Offset(medianX, cy - h * 0.45f),
                end = Offset(medianX, cy + h * 0.45f),
                strokeWidth = 2f,
            )

            // Domain axis baseline
            drawLine(
                color = line,
                start = Offset(0f, h - 1f),
                end = Offset(w, h - 1f),
                strokeWidth = 1f,
            )
        }

        Spacer(modifier = Modifier.height(6.dp))

        // 95% then 80% CI bars
        CredibleIntervalBar(
            lower = quantiles.p05,
            upper = quantiles.p95,
            domainMax = effectiveDomainMax,
            color = accent.copy(alpha = 0.55f),
            label = "95%",
            testTag = CI_95_TEST_TAG,
        )
        Spacer(modifier = Modifier.height(4.dp))
        CredibleIntervalBar(
            lower = quantiles.p10,
            upper = quantiles.p90,
            domainMax = effectiveDomainMax,
            color = accent,
            label = "80%",
            testTag = CI_80_TEST_TAG,
        )

        Spacer(modifier = Modifier.height(2.dp))
        val p50Pct = formatPercent(quantiles.p50)
        val p10Pct = formatPercent(quantiles.p10)
        val p90Pct = formatPercent(quantiles.p90)
        Text(
            text = "p50 = $p50Pct · p80 = $p10Pct–$p90Pct",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun CredibleIntervalBar(
    lower: Double,
    upper: Double,
    domainMax: Double,
    color: Color,
    label: String,
    testTag: String,
) {
    Canvas(
        modifier =
            Modifier
                .fillMaxWidth()
                .height(10.dp)
                .padding(vertical = 1.dp)
                .testTag(testTag)
                .semantics { contentDescription = "Intervalo de credibilidad $label" },
    ) {
        val w = size.width
        val h = size.height
        val cy = h / 2f
        val xLow = (min(lower, upper) / domainMax).toFloat().coerceIn(0f, 1f) * w
        val xHigh = (max(lower, upper) / domainMax).toFloat().coerceIn(0f, 1f) * w
        drawLine(
            color = color,
            start = Offset(xLow, cy),
            end = Offset(xHigh, cy),
            strokeWidth = h,
        )
    }
}

@Composable
fun PercentTick(value: Double) {
    Text(
        text = formatPercent(value),
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

internal fun formatPercent(fraction: Double): String = "%.1f%%".format(fraction * 100.0)

const val VIOLIN_TEST_TAG: String = "violin"
const val CI_80_TEST_TAG: String = "ci-80"
const val CI_95_TEST_TAG: String = "ci-95"
