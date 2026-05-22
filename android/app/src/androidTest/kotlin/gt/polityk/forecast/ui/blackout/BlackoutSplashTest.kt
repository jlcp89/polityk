package gt.polityk.forecast.ui.blackout

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import gt.polityk.forecast.ui.presidential.PresidentialScreen
import gt.polityk.forecast.ui.presidential.PresidentialUiState
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Rule
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class BlackoutSplashTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun renders_silencio_electoral_splash_in_spanish_with_legal_reference() {
        composeRule.setContent {
            PolitykTheme {
                BlackoutSplash(resumeAt = Instant.parse("2026-06-29T00:00:00Z"))
            }
        }
        composeRule.onNodeWithTag(BLACKOUT_SPLASH_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithText("Silencio Electoral").assertIsDisplayed()
        composeRule
            .onNodeWithText("Expediente 1699-2018 — Corte de Constitucionalidad de Guatemala")
            .assertIsDisplayed()
    }

    @Test
    fun renders_resume_timestamp_formatted_for_guatemala_locale() {
        composeRule.setContent {
            PolitykTheme {
                BlackoutSplash(resumeAt = Instant.parse("2026-06-29T00:00:00Z"))
            }
        }
        composeRule.onNodeWithTag(BLACKOUT_RESUME_TEST_TAG).assertIsDisplayed()
        // 2026-06-29T00:00Z == 2026-06-28 Sunday 18:00 GT
        val formatted = formatResumeAt(Instant.parse("2026-06-29T00:00:00Z"))
        composeRule.onNodeWithText(formatted).assertIsDisplayed()
    }

    @Test
    fun presidential_screen_renders_blackout_state_via_splash() {
        val resumeAt =
            BlackoutResumeCalculator.nextResumeInstant(
                Clock.fixed(Instant.parse("2026-06-27T14:00:00Z"), ZoneOffset.UTC),
            )
        composeRule.setContent {
            PolitykTheme {
                PresidentialScreen(
                    state = PresidentialUiState.Blackout(resumeAt),
                    onRetry = {},
                )
            }
        }
        composeRule.onNodeWithTag(BLACKOUT_SPLASH_TEST_TAG).assertIsDisplayed()
    }
}
