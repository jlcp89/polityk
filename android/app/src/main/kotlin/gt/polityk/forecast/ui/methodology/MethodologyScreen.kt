package gt.polityk.forecast.ui.methodology

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import gt.polityk.forecast.R
import gt.polityk.forecast.data.api.MethodologyPayload
import gt.polityk.forecast.data.api.PollsterBiasPrior
import gt.polityk.forecast.ui.common.RelativeTime
import gt.polityk.forecast.ui.presidential.formatPercent
import java.time.Clock

@Composable
fun MethodologyRoute(
    runIdHint: String? = null,
    onBack: () -> Unit = {},
    viewModel: MethodologyViewModel = hiltViewModel(),
    clock: Clock = remember { Clock.systemUTC() },
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    MethodologyScreen(
        state = state,
        runIdHint = runIdHint,
        clock = clock,
        onBack = onBack,
        onRetry = viewModel::load,
        onOpenLongForm = { url ->
            val intent =
                Intent(Intent.ACTION_VIEW, url.toUri()).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
            context.startActivity(intent)
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MethodologyScreen(
    state: MethodologyUiState,
    runIdHint: String?,
    clock: Clock,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onOpenLongForm: (String) -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.methodology_title)) },
                navigationIcon = {
                    IconButton(
                        onClick = onBack,
                        modifier = Modifier.testTag(METHODOLOGY_BACK_BUTTON_TEST_TAG),
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.back_content_description),
                        )
                    }
                },
            )
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when (state) {
                MethodologyUiState.Loading -> MethodologyLoading()
                is MethodologyUiState.Error -> MethodologyError(message = state.message, onRetry = onRetry)
                is MethodologyUiState.Ready ->
                    MethodologyReady(
                        payload = state.payload,
                        runIdHint = runIdHint,
                        clock = clock,
                        onOpenLongForm = onOpenLongForm,
                    )
            }
        }
    }
}

@Composable
private fun MethodologyLoading() {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .testTag(METHODOLOGY_LOADING_TEST_TAG),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(12.dp))
            Text(text = stringResource(R.string.state_loading))
        }
    }
}

@Composable
private fun MethodologyError(
    message: String,
    onRetry: () -> Unit,
) {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp)
                .testTag(METHODOLOGY_ERROR_TEST_TAG),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = stringResource(R.string.state_error_title),
                style = MaterialTheme.typography.titleMedium,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Button(onClick = onRetry) {
                Text(text = stringResource(R.string.state_error_retry))
            }
        }
    }
}

@Composable
private fun MethodologyReady(
    payload: MethodologyPayload,
    runIdHint: String?,
    clock: Clock,
    onOpenLongForm: (String) -> Unit,
) {
    LazyColumn(
        modifier =
            Modifier
                .fillMaxSize()
                .testTag(METHODOLOGY_READY_TEST_TAG),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        item { MethodologyHeader() }
        item { ModelVersionSection(modelVersion = payload.modelVersion, runIdHint = runIdHint) }
        item { GeneratedAtSection(generatedAt = payload.generatedAt, clock = clock) }
        item { PollsterBiasSection(priors = payload.presidential.pollsterBiasPriors) }
        item { FundamentalsSection(features = payload.presidential.fundamentalsFeatures) }
        item { SentimentSection(enabled = payload.presidential.sentimentAsModelledInput) }
        item { LongFormSection(url = payload.longFormUrl, onOpen = { onOpenLongForm(payload.longFormUrl) }) }
    }
}

@Composable
private fun MethodologyHeader() {
    Column {
        Text(
            text = stringResource(R.string.methodology_title),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.methodology_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ModelVersionSection(
    modelVersion: String,
    runIdHint: String?,
) {
    SectionCard(
        title = stringResource(R.string.methodology_section_model_version),
        testTag = METHODOLOGY_SECTION_MODEL_VERSION,
    ) {
        Text(
            text = stringResource(R.string.model_version_label) + ": " + modelVersion,
            style = MaterialTheme.typography.bodyMedium,
        )
        if (runIdHint != null) {
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = stringResource(R.string.run_id_label) + ": " + shortRunId(runIdHint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag(METHODOLOGY_RUN_ID_TEST_TAG),
            )
        }
    }
}

@Composable
private fun GeneratedAtSection(
    generatedAt: String,
    clock: Clock,
) {
    val relative = RelativeTime.formatSpanish(generatedAt, clock)
    SectionCard(
        title = stringResource(R.string.methodology_section_generated_at),
        testTag = METHODOLOGY_SECTION_GENERATED_AT,
    ) {
        if (relative != null) {
            Text(
                text = relative,
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.testTag(METHODOLOGY_RELATIVE_STAMP_TEST_TAG),
            )
            Spacer(modifier = Modifier.height(2.dp))
        }
        Text(
            text = generatedAt,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PollsterBiasSection(priors: List<PollsterBiasPrior>) {
    SectionCard(
        title = stringResource(R.string.methodology_section_pollster_bias),
        testTag = METHODOLOGY_SECTION_POLLSTER_BIAS,
    ) {
        Text(
            text = stringResource(R.string.methodology_pollster_table_header),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.height(6.dp))
        priors.forEach { prior ->
            PollsterRow(prior = prior)
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
            )
        }
    }
}

@Composable
private fun PollsterRow(prior: PollsterBiasPrior) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp).testTag(pollsterRowTag(prior.pollster)),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = prior.pollster,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
        )
        Text(
            text = "${formatSigned(prior.historicalBiasMean)} · ${formatPercent(prior.historicalBiasSd)} · n=${prior.sampleCountUsed}",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun FundamentalsSection(features: List<String>) {
    SectionCard(
        title = stringResource(R.string.methodology_section_fundamentals),
        testTag = METHODOLOGY_SECTION_FUNDAMENTALS,
    ) {
        features.forEach { feature ->
            Text(
                text = "• $feature",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(vertical = 2.dp),
            )
        }
    }
}

@Composable
private fun SentimentSection(enabled: Boolean) {
    val label =
        if (enabled) {
            stringResource(R.string.methodology_sentiment_on)
        } else {
            stringResource(R.string.methodology_sentiment_off)
        }
    SectionCard(
        title = stringResource(R.string.methodology_section_sentiment),
        testTag = METHODOLOGY_SECTION_SENTIMENT,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.testTag(METHODOLOGY_SENTIMENT_VALUE_TEST_TAG),
        )
    }
}

@Composable
private fun LongFormSection(
    url: String,
    onOpen: () -> Unit,
) {
    SectionCard(
        title = stringResource(R.string.methodology_section_long_form),
        testTag = METHODOLOGY_SECTION_LONG_FORM,
    ) {
        Text(
            text = url,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag(METHODOLOGY_LONG_FORM_URL_TEST_TAG),
        )
        Spacer(modifier = Modifier.height(8.dp))
        Button(
            onClick = onOpen,
            modifier = Modifier.testTag(METHODOLOGY_LONG_FORM_BUTTON_TEST_TAG),
        ) {
            Text(text = stringResource(R.string.methodology_open_long_form))
        }
    }
}

@Composable
private fun SectionCard(
    title: String,
    testTag: String,
    content: @Composable () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth().testTag(testTag)) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(modifier = Modifier.height(8.dp))
        content()
    }
}

fun shortRunId(runId: String): String {
    val firstSegment = runId.substringBefore('-', missingDelimiterValue = runId)
    return firstSegment.take(SHORT_RUN_ID_LEN)
}

internal fun formatSigned(value: Double): String {
    val pct = value * PCT_SCALE
    val sign = if (pct >= 0.0) "+" else ""
    return "$sign${"%.1f".format(pct)}pp"
}

fun pollsterRowTag(pollster: String): String = "methodology-pollster-row-$pollster"

const val METHODOLOGY_LOADING_TEST_TAG: String = "methodology-state-loading"
const val METHODOLOGY_ERROR_TEST_TAG: String = "methodology-state-error"
const val METHODOLOGY_READY_TEST_TAG: String = "methodology-state-ready"
const val METHODOLOGY_SECTION_MODEL_VERSION: String = "methodology-section-model-version"
const val METHODOLOGY_SECTION_GENERATED_AT: String = "methodology-section-generated-at"
const val METHODOLOGY_SECTION_POLLSTER_BIAS: String = "methodology-section-pollster-bias"
const val METHODOLOGY_SECTION_FUNDAMENTALS: String = "methodology-section-fundamentals"
const val METHODOLOGY_SECTION_SENTIMENT: String = "methodology-section-sentiment"
const val METHODOLOGY_SECTION_LONG_FORM: String = "methodology-section-long-form"
const val METHODOLOGY_RUN_ID_TEST_TAG: String = "methodology-run-id"
const val METHODOLOGY_RELATIVE_STAMP_TEST_TAG: String = "methodology-relative-stamp"
const val METHODOLOGY_SENTIMENT_VALUE_TEST_TAG: String = "methodology-sentiment-value"
const val METHODOLOGY_LONG_FORM_URL_TEST_TAG: String = "methodology-long-form-url"
const val METHODOLOGY_LONG_FORM_BUTTON_TEST_TAG: String = "methodology-long-form-button"
const val METHODOLOGY_BACK_BUTTON_TEST_TAG: String = "methodology-back-button"

private const val SHORT_RUN_ID_LEN = 8
private const val PCT_SCALE = 100.0
