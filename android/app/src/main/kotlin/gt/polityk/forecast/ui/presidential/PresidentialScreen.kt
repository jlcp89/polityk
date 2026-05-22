package gt.polityk.forecast.ui.presidential

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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import gt.polityk.forecast.R
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.PresidentialPayload
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
                is PresidentialUiState.Ready -> ReadyContent(payload = state.payload, clock = clock)
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
private fun ReadyContent(
    payload: PresidentialPayload,
    clock: Clock,
) {
    val sorted = payload.candidates.sortedByDescending { it.voteShare.p50 }
    LazyColumn(
        modifier =
            Modifier
                .fillMaxSize()
                .testTag(READY_TEST_TAG),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        item { Header(payload = payload, clock = clock) }
        items(items = sorted, key = Candidate::candidateId) { candidate ->
            CandidateRow(candidate = candidate)
        }
        item {
            RunoffMatrixSection(
                candidates = payload.candidates,
                runoffMatrix = payload.runoffMatrix,
            )
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
