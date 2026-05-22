package gt.polityk.forecast.ui.presidential

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.api.Race
import gt.polityk.forecast.data.api.RunoffPair
import gt.polityk.forecast.data.api.VoteShareQuantiles
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Rule
import org.junit.Test

class PresidentialScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun renders_five_candidate_fixture_with_violin_and_both_ci_bars_per_candidate() {
        val payload = fivePresidentialCandidatesFixture()

        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(
                    state = PresidentialUiState.Ready(payload),
                    onRetry = {},
                )
            }
        }

        // Each of the five candidate rows is present and visible.
        composeRule.onNodeWithTag(READY_TEST_TAG).assertIsDisplayed()
        payload.candidates.forEach { c ->
            composeRule.onNodeWithText(c.name).assertIsDisplayed()
            composeRule.onNodeWithText(c.partyName).assertIsDisplayed()
            composeRule.onNodeWithTag(candidateRowTag(c.candidateId)).assertIsDisplayed()
        }

        // One violin + one 80% CI bar + one 95% CI bar per candidate.
        composeRule.onAllNodesWithTag(VIOLIN_TEST_TAG).assertCountEquals(payload.candidates.size)
        composeRule.onAllNodesWithTag(CI_80_TEST_TAG).assertCountEquals(payload.candidates.size)
        composeRule.onAllNodesWithTag(CI_95_TEST_TAG).assertCountEquals(payload.candidates.size)
    }

    @Test
    fun renders_loading_state_then_replaced_by_ready() {
        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = PresidentialUiState.Loading, onRetry = {})
            }
        }
        composeRule.onNodeWithTag(LOADING_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun renders_error_state_with_retry() {
        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = PresidentialUiState.Error("network down"), onRetry = {})
            }
        }
        composeRule.onNodeWithTag(ERROR_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithText("network down").assertIsDisplayed()
    }

    private fun fivePresidentialCandidatesFixture(): PresidentialPayload =
        PresidentialPayload(
            runId = "00000000-0000-0000-0000-000000000001",
            modelVersion = "0.1.0-test",
            generatedAt = "2026-05-22T12:00:00Z",
            race = Race(type = "presidential", cycle = 2027, round = 1),
            candidates =
                listOf(
                    candidate(42, "Bernardo Arévalo", "Movimiento Semilla", 0.12, 0.14, 0.18, 0.23, 0.28, 0.32, 0.34, 0.04, 0.62),
                    candidate(11, "Sandra Torres", "UNE", 0.10, 0.12, 0.16, 0.20, 0.24, 0.28, 0.30, 0.02, 0.55),
                    candidate(19, "Zury Ríos", "Valor", 0.07, 0.09, 0.11, 0.14, 0.17, 0.19, 0.21, 0.01, 0.31),
                    candidate(23, "Edmond Mulet", "Cabal", 0.05, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.005, 0.18),
                    candidate(31, "Manuel Conde", "Vamos", 0.03, 0.04, 0.05, 0.07, 0.09, 0.11, 0.12, 0.001, 0.09),
                ),
            runoffMatrix =
                listOf(
                    RunoffPair(42, 11, 0.31, 0.61),
                    RunoffPair(42, 19, 0.18, 0.55),
                ),
            interventionsApplied = emptyList(),
            methodologyUrl = "https://polityk.gt/methodology",
            cacheInvalidUntil = null,
        )

    @Suppress("LongParameterList")
    private fun candidate(
        id: Long,
        name: String,
        party: String,
        p05: Double,
        p10: Double,
        p25: Double,
        p50: Double,
        p75: Double,
        p90: Double,
        p95: Double,
        winRound1: Double,
        runoffProb: Double,
    ): Candidate =
        Candidate(
            candidateId = id,
            name = name,
            wikidataQid = null,
            partyId = id * 100,
            partyName = party,
            voteShare = VoteShareQuantiles(p05, p10, p25, p50, p75, p90, p95),
            winProbabilityRound1 = winRound1,
            qualifiesForRunoffProbability = runoffProb,
        )
}
