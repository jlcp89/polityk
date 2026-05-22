package gt.polityk.forecast.ui.presidential

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Description
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import gt.polityk.forecast.R
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.ui.blackout.BlackoutSplash
import gt.polityk.forecast.ui.common.RelativeTime
import java.time.Clock

@Composable
fun PresidentialRoute(
    viewModel: PresidentialViewModel = hiltViewModel(),
    onOpenMethodology: () -> Unit = {},
    clock: Clock = remember { Clock.systemUTC() },
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    PresidentialScreen(
        state = state,
        clock = clock,
        onRetry = viewModel::load,
        onOpenMethodology = onOpenMethodology,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PresidentialScreen(
    state: PresidentialUiState,
    onRetry: () -> Unit,
    clock: Clock = Clock.systemUTC(),
    onOpenMethodology: () -> Unit = {},
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.presidential_title)) },
                actions = {
                    IconButton(
                        onClick = onOpenMethodology,
                        modifier = Modifier.testTag(METHODOLOGY_ICON_TEST_TAG),
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.Description,
                            contentDescription = stringResource(R.string.open_methodology_content_description),
                        )
                    }
                },
            )
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when (state) {
                PresidentialUiState.Loading -> LoadingState()
                is PresidentialUiState.Error -> ErrorState(message = state.message, onRetry = onRetry)
                PresidentialUiState.NoRecentData -> NoRecentDataState(onRetry = onRetry)
                is PresidentialUiState.Loaded -> LoadedContent(state = state, onRetry = onRetry, clock = clock)
                is PresidentialUiState.Blackout -> BlackoutSplash(resumeAt = state.resumeAt)
            }
        }
    }
}

@Composable
private fun LoadingState() {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .testTag(LOADING_TEST_TAG),
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
private fun ErrorState(
    message: String,
    onRetry: () -> Unit,
) {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp)
                .testTag(ERROR_TEST_TAG),
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
private fun NoRecentDataState(onRetry: () -> Unit) {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp)
                .testTag(NO_RECENT_DATA_TEST_TAG),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = stringResource(R.string.no_recent_data_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.no_recent_data_body),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Button(
                modifier = Modifier.testTag(NO_RECENT_DATA_RETRY_TAG),
                onClick = onRetry,
            ) {
                Text(text = stringResource(R.string.state_error_retry))
            }
        }
    }
}

@Composable
private fun LoadedContent(
    state: PresidentialUiState.Loaded,
    onRetry: () -> Unit,
    clock: Clock,
) {
    val sorted = state.payload.candidates.sortedByDescending { it.voteShare.p50 }
    LazyColumn(
        modifier =
            Modifier
                .fillMaxSize()
                .testTag(READY_TEST_TAG),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        item { FreshnessBanner(state = state, onRetry = onRetry) }
        item { Header(payload = state.payload, clock = clock) }
        items(items = sorted, key = Candidate::candidateId) { candidate ->
            CandidateRow(candidate = candidate)
        }
        item {
            RunoffMatrixSection(
                candidates = state.payload.candidates,
                runoffMatrix = state.payload.runoffMatrix,
            )
        }
    }
}

@Composable
private fun FreshnessBanner(
    state: PresidentialUiState.Loaded,
    onRetry: () -> Unit,
) {
    when (state) {
        is PresidentialUiState.Fresh -> Unit
        is PresidentialUiState.SlightlyStale ->
            Banner(
                color = BANNER_YELLOW,
                textColor = BANNER_YELLOW_TEXT,
                tag = BANNER_YELLOW_TEST_TAG,
                message = stringResource(R.string.banner_slightly_stale, state.ageHours),
                onRetry = null,
            )
        is PresidentialUiState.Stale ->
            Banner(
                color = BANNER_RED,
                textColor = BANNER_RED_TEXT,
                tag = BANNER_RED_TEST_TAG,
                message = stringResource(R.string.banner_stale, state.ageHours),
                onRetry = onRetry,
            )
    }
}

@Composable
private fun Banner(
    color: Color,
    textColor: Color,
    tag: String,
    message: String,
    onRetry: (() -> Unit)?,
) {
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .background(color = color, shape = RoundedCornerShape(8.dp))
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .testTag(tag),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = textColor,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.fillMaxWidth(if (onRetry != null) WEIGHT_TEXT_WITH_RETRY else 1f),
        )
        if (onRetry != null) {
            Button(
                modifier = Modifier.testTag(BANNER_RETRY_TAG),
                onClick = onRetry,
            ) {
                Text(text = stringResource(R.string.state_error_retry))
            }
        }
    }
}

@Composable
private fun Header(
    payload: PresidentialPayload,
    clock: Clock,
) {
    Column {
        Text(
            text = stringResource(R.string.presidential_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.height(8.dp))
        val relative = RelativeTime.formatSpanish(payload.generatedAt, clock)
        if (relative != null) {
            Text(
                text = stringResource(R.string.last_updated_label) + " " + relative,
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.testTag(LAST_UPDATED_STAMP_TEST_TAG),
            )
            Spacer(modifier = Modifier.height(4.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            MetaTag(label = stringResource(R.string.model_version_label), value = payload.modelVersion)
            MetaTag(label = stringResource(R.string.generated_at_label), value = payload.generatedAt)
        }
    }
}

@Composable
private fun MetaTag(
    label: String,
    value: String,
) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(text = value, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun CandidateRow(candidate: Candidate) {
    Column(modifier = Modifier.fillMaxWidth().testTag(candidateRowTag(candidate.candidateId))) {
        Row(verticalAlignment = Alignment.Bottom) {
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = candidate.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = candidate.partyName,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        VoteShareDistribution(quantiles = candidate.voteShare)
        Spacer(modifier = Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            ProbabilityTag(
                modifier = Modifier.testTag(runoffQualifyBadgeTag(candidate.candidateId)),
                label = stringResource(R.string.runoff_qualifies_label),
                value = candidate.qualifiesForRunoffProbability,
            )
            ProbabilityTag(
                label = stringResource(R.string.win_round_1_label),
                value = candidate.winProbabilityRound1,
            )
        }
        Spacer(modifier = Modifier.height(12.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
    }
}

@Composable
private fun ProbabilityTag(
    label: String,
    value: Double,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = formatPercent(value),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Medium,
        )
    }
}

fun candidateRowTag(candidateId: Long): String = "candidate-row-$candidateId"

fun runoffQualifyBadgeTag(candidateId: Long): String = "runoff-qualify-badge-$candidateId"

const val LOADING_TEST_TAG: String = "state-loading"
const val ERROR_TEST_TAG: String = "state-error"
const val READY_TEST_TAG: String = "state-ready"
const val METHODOLOGY_ICON_TEST_TAG: String = "presidential-methodology-icon"
const val LAST_UPDATED_STAMP_TEST_TAG: String = "presidential-last-updated"
const val LAST_UPDATED_STAMP_TAG: String = "presidential-last-updated"
const val NO_RECENT_DATA_TEST_TAG: String = "state-no-recent-data"
const val NO_RECENT_DATA_RETRY_TAG: String = "no-recent-data-retry"
const val BANNER_YELLOW_TEST_TAG: String = "banner-slightly-stale"
const val BANNER_RED_TEST_TAG: String = "banner-stale"
const val BANNER_RETRY_TAG: String = "banner-retry"

private val BANNER_YELLOW = Color(0xFFFFF3CD)
private val BANNER_YELLOW_TEXT = Color(0xFF664D03)
private val BANNER_RED = Color(0xFFF8D7DA)
private val BANNER_RED_TEXT = Color(0xFF842029)
private const val WEIGHT_TEXT_WITH_RETRY = 0.65f
