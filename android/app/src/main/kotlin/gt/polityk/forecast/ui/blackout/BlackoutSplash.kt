package gt.polityk.forecast.ui.blackout

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import gt.polityk.forecast.R
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Full-screen legal-silence splash per ADR-003 / ADR-014.
 *
 * All text comes from in-app `strings.xml` — the API 503 response body is
 * never trusted for splash content. The resume timestamp is computed
 * locally by [BlackoutResumeCalculator].
 */
@Composable
fun BlackoutSplash(resumeAt: Instant) {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp)
                .testTag(BLACKOUT_SPLASH_TEST_TAG),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = stringResource(R.string.blackout_title),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,
                modifier = Modifier.testTag(BLACKOUT_TITLE_TEST_TAG),
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.blackout_body),
                style = MaterialTheme.typography.bodyLarge,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                text = stringResource(R.string.blackout_legal_reference),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(24.dp))
            Text(
                text = stringResource(R.string.blackout_resume_label),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                text = formatResumeAt(resumeAt),
                style = MaterialTheme.typography.titleMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.testTag(BLACKOUT_RESUME_TEST_TAG),
            )
        }
    }
}

internal fun formatResumeAt(resumeAt: Instant): String {
    val zoned = resumeAt.atZone(BlackoutResumeCalculator.GUATEMALA_ZONE)
    return RESUME_FORMATTER.format(zoned)
}

private val RESUME_FORMATTER: DateTimeFormatter =
    DateTimeFormatter.ofPattern("EEEE d 'de' MMMM, HH:mm 'GT'", Locale.forLanguageTag("es"))

const val BLACKOUT_SPLASH_TEST_TAG: String = "blackout-splash"
const val BLACKOUT_TITLE_TEST_TAG: String = "blackout-title"
const val BLACKOUT_RESUME_TEST_TAG: String = "blackout-resume"
