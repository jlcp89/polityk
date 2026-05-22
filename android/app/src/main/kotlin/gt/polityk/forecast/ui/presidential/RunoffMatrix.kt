package gt.polityk.forecast.ui.presidential

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import gt.polityk.forecast.R
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.RunoffPair

const val MAX_RUNOFF_PAIRS_SHOWN: Int = 5
const val RUNOFF_MATRIX_TEST_TAG: String = "runoff-matrix"
const val RUNOFF_MATRIX_EMPTY_TEST_TAG: String = "runoff-matrix-empty"

fun runoffPairRowTag(
    aId: Long,
    bId: Long,
): String = "runoff-row-$aId-$bId"

/**
 * Sort by `pair_probability` descending and cap to the top N pairs.
 *
 * Stable for ties: `sortedByDescending` preserves input order among equal keys,
 * so identical pair probabilities render in the order they arrive from the API.
 */
fun topRunoffPairs(
    matrix: List<RunoffPair>,
    max: Int = MAX_RUNOFF_PAIRS_SHOWN,
): List<RunoffPair> = matrix.sortedByDescending { it.pairProbability }.take(max)

@Composable
fun RunoffMatrixSection(
    candidates: List<Candidate>,
    runoffMatrix: List<RunoffPair>,
    modifier: Modifier = Modifier,
) {
    val namesById =
        remember(candidates) {
            candidates.associateBy({ it.candidateId }, { it.name })
        }
    Column(
        modifier =
            modifier
                .fillMaxWidth()
                .testTag(RUNOFF_MATRIX_TEST_TAG),
    ) {
        Text(
            text = stringResource(R.string.runoff_matrix_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(modifier = Modifier.height(8.dp))
        if (runoffMatrix.isEmpty()) {
            Text(
                modifier = Modifier.testTag(RUNOFF_MATRIX_EMPTY_TEST_TAG),
                text = stringResource(R.string.runoff_matrix_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                topRunoffPairs(runoffMatrix).forEach { pair ->
                    RunoffPairRow(pair = pair, namesById = namesById)
                }
            }
        }
    }
}

@Composable
private fun RunoffPairRow(
    pair: RunoffPair,
    namesById: Map<Long, String>,
) {
    val nameA = namesById[pair.candidateAId] ?: "#${pair.candidateAId}"
    val nameB = namesById[pair.candidateBId] ?: "#${pair.candidateBId}"
    val rowText =
        stringResource(
            R.string.runoff_matrix_row_format,
            nameA,
            nameB,
            formatPercent(pair.pairProbability),
            nameA,
            formatPercent(pair.winnerAProbability),
        )
    Text(
        modifier =
            Modifier
                .fillMaxWidth()
                .testTag(runoffPairRowTag(pair.candidateAId, pair.candidateBId)),
        text = rowText,
        style = MaterialTheme.typography.bodyMedium,
    )
}
