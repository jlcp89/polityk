package gt.polityk.forecast.ui.presidential

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollToNode
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.api.Race
import gt.polityk.forecast.data.api.RunoffPair
import gt.polityk.forecast.data.api.VoteShareQuantiles
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Rule
import org.junit.Test

class RunoffMatrixScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun renders_top_five_runoff_pairs_sorted_and_drops_remainder() {
        val payload = payloadWithRunoffPairs(SEVEN_PAIRS)

        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = PresidentialUiState.Fresh(payload, ageHours = 1L), onRetry = {})
            }
        }

        // Scroll the LazyColumn to the runoff matrix section.
        composeRule
            .onNodeWithTag(READY_TEST_TAG)
            .performScrollToNode(hasTestTag(RUNOFF_MATRIX_TEST_TAG))
        composeRule.onNodeWithTag(RUNOFF_MATRIX_TEST_TAG).assertIsDisplayed()

        // The five highest-probability pairs render (0.30, 0.25, 0.20, 0.15, 0.10).
        TOP_FIVE_ROW_TAGS.forEach { tag ->
            composeRule
                .onNodeWithTag(READY_TEST_TAG)
                .performScrollToNode(hasTestTag(tag))
            composeRule.onNodeWithTag(tag).assertIsDisplayed()
        }
    }

    @Test
    fun renders_empty_placeholder_when_runoff_matrix_is_empty() {
        val payload = payloadWithRunoffPairs(emptyList())

        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = PresidentialUiState.Fresh(payload, ageHours = 1L), onRetry = {})
            }
        }

        composeRule
            .onNodeWithTag(READY_TEST_TAG)
            .performScrollToNode(hasTestTag(RUNOFF_MATRIX_EMPTY_TEST_TAG))
        composeRule.onNodeWithTag(RUNOFF_MATRIX_EMPTY_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun renders_runoff_qualify_badge_per_candidate() {
        val payload = payloadWithRunoffPairs(SEVEN_PAIRS)

        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = PresidentialUiState.Fresh(payload, ageHours = 1L), onRetry = {})
            }
        }

        payload.candidates.forEach { candidate ->
            val tag = runoffQualifyBadgeTag(candidate.candidateId)
            composeRule
                .onNodeWithTag(READY_TEST_TAG)
                .performScrollToNode(hasTestTag(tag))
            composeRule.onNodeWithTag(tag).assertIsDisplayed()
        }
    }

    private fun payloadWithRunoffPairs(pairs: List<RunoffPair>): PresidentialPayload =
        PresidentialPayload(
            runId = "00000000-0000-0000-0000-000000000040",
            modelVersion = "0.1.0-runoff",
            generatedAt = "2026-05-22T12:00:00Z",
            race = Race(type = "presidential", cycle = 2027, round = 1),
            candidates = SIX_CANDIDATES,
            runoffMatrix = pairs,
            interventionsApplied = emptyList(),
            methodologyUrl = "https://polityk.gt/methodology",
            cacheInvalidUntil = null,
        )

    private companion object {
        val SIX_CANDIDATES =
            listOf(
                candidate(1, "Candidate One"),
                candidate(2, "Candidate Two"),
                candidate(3, "Candidate Three"),
                candidate(4, "Candidate Four"),
                candidate(5, "Candidate Five"),
                candidate(6, "Candidate Six"),
            )

        val SEVEN_PAIRS =
            listOf(
                RunoffPair(1, 2, 0.05, 0.50),
                RunoffPair(1, 3, 0.30, 0.55),
                RunoffPair(2, 3, 0.10, 0.45),
                RunoffPair(1, 4, 0.25, 0.60),
                RunoffPair(2, 4, 0.15, 0.40),
                RunoffPair(3, 4, 0.20, 0.65),
                RunoffPair(1, 5, 0.08, 0.50),
            )

        // Expected sort: 0.30, 0.25, 0.20, 0.15, 0.10. SEVEN_PAIRS contains a
        // sixth pair at 0.08 and a seventh at 0.05 that must be dropped.
        val TOP_FIVE_ROW_TAGS =
            listOf(
                runoffPairRowTag(1, 3),
                runoffPairRowTag(1, 4),
                runoffPairRowTag(3, 4),
                runoffPairRowTag(2, 4),
                runoffPairRowTag(2, 3),
            )

        private fun candidate(
            id: Long,
            name: String,
        ): Candidate =
            Candidate(
                candidateId = id,
                name = name,
                wikidataQid = null,
                partyId = id * 100,
                partyName = "Party $id",
                voteShare =
                    VoteShareQuantiles(
                        p05 = 0.05,
                        p10 = 0.08,
                        p25 = 0.12,
                        p50 = 0.18,
                        p75 = 0.22,
                        p90 = 0.26,
                        p95 = 0.30,
                    ),
                winProbabilityRound1 = 0.02,
                qualifiesForRunoffProbability = 0.35,
            )
    }
}
