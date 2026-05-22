package gt.polityk.forecast.ui.presidential

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import gt.polityk.forecast.data.api.Candidate
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.api.Race
import gt.polityk.forecast.data.api.VoteShareQuantiles
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

/**
 * Compose UI test for ADR-018 graduated freshness banners.
 *
 * Each test renders the screen by deriving the UI state from a fixture payload
 * and an injected [Clock]. Same payload, different clocks → different buckets.
 * This is the "time-warp" path required by issue #42.
 */
class FreshnessBannerScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    private val payload = singleCandidateFixture()
    private val generatedAtMs = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli()

    @Test
    fun fresh_bucket_renders_no_banner_and_shows_last_updated_stamp() {
        val state = renderAt("2026-05-22T13:00:00Z")
        check(state is PresidentialUiState.Fresh) { "expected Fresh, got $state" }
        composeRule.onNodeWithTag(READY_TEST_TAG).assertIsDisplayed()
        composeRule.onAllNodesWithTag(BANNER_YELLOW_TEST_TAG).assertCountEquals(0)
        composeRule.onAllNodesWithTag(BANNER_RED_TEST_TAG).assertCountEquals(0)
        composeRule.onNodeWithTag(LAST_UPDATED_STAMP_TAG).assertIsDisplayed()
    }

    @Test
    fun slightly_stale_bucket_renders_yellow_banner() {
        val state = renderAt("2026-05-23T00:00:00Z")
        check(state is PresidentialUiState.SlightlyStale) { "expected SlightlyStale, got $state" }
        composeRule.onNodeWithTag(READY_TEST_TAG).performScrollToNode(hasTestTag(BANNER_YELLOW_TEST_TAG))
        composeRule.onNodeWithTag(BANNER_YELLOW_TEST_TAG).assertIsDisplayed()
        composeRule.onAllNodesWithTag(BANNER_RED_TEST_TAG).assertCountEquals(0)
    }

    @Test
    fun stale_bucket_renders_red_banner_with_prominent_retry() {
        val state = renderAt("2026-05-24T12:00:00Z")
        check(state is PresidentialUiState.Stale) { "expected Stale, got $state" }
        composeRule.onNodeWithTag(READY_TEST_TAG).performScrollToNode(hasTestTag(BANNER_RED_TEST_TAG))
        composeRule.onNodeWithTag(BANNER_RED_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(BANNER_RETRY_TAG).assertIsDisplayed()
    }

    @Test
    fun no_recent_data_bucket_suppresses_forecast_and_retry_button_works() {
        val state =
            bucketize(
                payload = payload,
                generatedAtMs = generatedAtMs,
                cacheInvalidUntilMs = null,
                nowMs = Instant.parse("2026-05-26T12:00:00Z").toEpochMilli(),
            )
        assertEquals(PresidentialUiState.NoRecentData, state)

        var retryClicks = 0
        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = state, onRetry = { retryClicks++ })
            }
        }

        composeRule.onNodeWithTag(NO_RECENT_DATA_TEST_TAG).assertIsDisplayed()
        composeRule.onAllNodesWithTag(READY_TEST_TAG).assertCountEquals(0)
        composeRule.onNodeWithTag(NO_RECENT_DATA_RETRY_TAG).performClick()
        assertEquals(1, retryClicks)
    }

    @Test
    fun cache_invalid_until_in_the_past_forces_no_recent_data_even_when_age_is_fresh() {
        val state =
            bucketize(
                payload = payload,
                generatedAtMs = generatedAtMs,
                cacheInvalidUntilMs = Instant.parse("2026-05-22T12:30:00Z").toEpochMilli(),
                nowMs = Instant.parse("2026-05-22T13:00:00Z").toEpochMilli(),
            )
        assertEquals(PresidentialUiState.NoRecentData, state)

        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = state, onRetry = {})
            }
        }
        composeRule.onNodeWithTag(NO_RECENT_DATA_TEST_TAG).assertIsDisplayed()
    }

    private fun renderAt(nowIso: String): PresidentialUiState {
        val clock = Clock.fixed(Instant.parse(nowIso), ZoneOffset.UTC)
        val state =
            bucketize(
                payload = payload,
                generatedAtMs = generatedAtMs,
                cacheInvalidUntilMs = null,
                nowMs = clock.millis(),
            )
        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(state = state, onRetry = {})
            }
        }
        return state
    }

    private fun singleCandidateFixture(): PresidentialPayload =
        PresidentialPayload(
            runId = "00000000-0000-0000-0000-0000000000aa",
            modelVersion = "0.1.0-test",
            generatedAt = "2026-05-22T12:00:00Z",
            race = Race(type = "presidential", cycle = 2027, round = 1),
            candidates =
                listOf(
                    Candidate(
                        candidateId = 1L,
                        name = "Test Candidate",
                        wikidataQid = null,
                        partyId = 100L,
                        partyName = "Test Party",
                        voteShare = VoteShareQuantiles(0.1, 0.12, 0.15, 0.2, 0.25, 0.28, 0.3),
                        winProbabilityRound1 = 0.1,
                        qualifiesForRunoffProbability = 0.5,
                    ),
                ),
            runoffMatrix = emptyList(),
            interventionsApplied = emptyList(),
            methodologyUrl = "https://polityk.gt/methodology",
            cacheInvalidUntil = null,
        )
}
