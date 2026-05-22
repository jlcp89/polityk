package gt.polityk.forecast.ui.methodology

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import gt.polityk.forecast.data.api.CalibrationThresholds
import gt.polityk.forecast.data.api.MethodologyPayload
import gt.polityk.forecast.data.api.PollsterBiasPrior
import gt.polityk.forecast.data.api.PresidentialMethodology
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class MethodologyScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun renders_all_six_sections_for_fixture_payload() {
        val payload = methodologyFixture()
        val clock = Clock.fixed(Instant.parse("2026-05-22T12:00:00Z"), ZoneOffset.UTC)

        composeRule.setContent {
            PolitykTheme {
                MethodologyScreen(
                    state = MethodologyUiState.Ready(payload),
                    runIdHint = "3f4e7c0a-1234-5678-9abc-def012345678",
                    clock = clock,
                    onBack = {},
                    onRetry = {},
                    onOpenLongForm = {},
                )
            }
        }

        composeRule.onNodeWithTag(METHODOLOGY_READY_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_MODEL_VERSION).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_GENERATED_AT).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_POLLSTER_BIAS).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_FUNDAMENTALS).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_SENTIMENT).assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_SECTION_LONG_FORM).assertIsDisplayed()

        // run_id displayed in short form (first 8 chars of UUID)
        composeRule.onNodeWithTag(METHODOLOGY_RUN_ID_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithText("ID de corrida: 3f4e7c0a").assertIsDisplayed()

        // generated_at relative + absolute (six hours)
        composeRule.onNodeWithTag(METHODOLOGY_RELATIVE_STAMP_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithText("hace 6 horas").assertIsDisplayed()
        composeRule.onNodeWithText("2026-05-22T06:00:00Z").assertIsDisplayed()

        // sentiment-inclusion status shows the off label for this fixture
        composeRule
            .onNodeWithText("Solo informativo (peso modelado = 0)")
            .assertIsDisplayed()

        // every pollster row is rendered
        composeRule
            .onAllNodesWithTag(pollsterRowTag("ProDatos"))
            .assertCountEquals(1)
        composeRule
            .onAllNodesWithTag(pollsterRowTag("CID Gallup"))
            .assertCountEquals(1)

        // every fundamentals feature is rendered as a bullet line
        composeRule.onNodeWithText("• incumbent_party").assertIsDisplayed()
        composeRule.onNodeWithText("• sentiment_trend_30d").assertIsDisplayed()

        // long-form URL is visible and the button is present
        composeRule.onNodeWithTag(METHODOLOGY_LONG_FORM_URL_TEST_TAG).assertIsDisplayed()
        composeRule
            .onNodeWithText("https://polityk.gt/methodology#presidential-0.1.0")
            .assertIsDisplayed()
        composeRule.onNodeWithTag(METHODOLOGY_LONG_FORM_BUTTON_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun open_long_form_button_invokes_callback_with_payload_url() {
        val payload = methodologyFixture()
        var openedUrl: String? = null

        composeRule.setContent {
            PolitykTheme {
                MethodologyScreen(
                    state = MethodologyUiState.Ready(payload),
                    runIdHint = null,
                    clock = Clock.fixed(Instant.parse("2026-05-22T12:00:00Z"), ZoneOffset.UTC),
                    onBack = {},
                    onRetry = {},
                    onOpenLongForm = { openedUrl = it },
                )
            }
        }

        composeRule
            .onNodeWithTag(METHODOLOGY_LONG_FORM_BUTTON_TEST_TAG)
            .performClick()

        assertEquals(payload.longFormUrl, openedUrl)
    }

    @Test
    fun relative_stamp_updates_across_hour_day_buckets() {
        val payload = methodologyFixture()
        val cases =
            listOf(
                Pair("2026-05-22T11:30:00Z", "hace unos minutos"),
                Pair("2026-05-22T11:00:00Z", "hace 1 hora"),
                Pair("2026-05-22T06:00:00Z", "hace 6 horas"),
                Pair("2026-05-21T12:00:00Z", "hace 1 día"),
            )
        cases.forEach { (generated, expected) ->
            val fixed = Clock.fixed(Instant.parse("2026-05-22T12:00:00Z"), ZoneOffset.UTC)
            val mutated = payload.copy(generatedAt = generated)

            composeRule.setContent {
                PolitykTheme {
                    MethodologyScreen(
                        state = MethodologyUiState.Ready(mutated),
                        runIdHint = null,
                        clock = fixed,
                        onBack = {},
                        onRetry = {},
                        onOpenLongForm = {},
                    )
                }
            }

            composeRule.onNodeWithText(expected).assertIsDisplayed()
        }
    }

    private fun methodologyFixture(): MethodologyPayload =
        MethodologyPayload(
            modelVersion = "0.1.0",
            generatedAt = "2026-05-22T06:00:00Z",
            presidential =
                PresidentialMethodology(
                    pollsterBiasPriors =
                        listOf(
                            PollsterBiasPrior(
                                pollster = "ProDatos",
                                historicalBiasMean = 0.063,
                                historicalBiasSd = 0.04,
                                sampleCountUsed = 8,
                            ),
                            PollsterBiasPrior(
                                pollster = "CID Gallup",
                                historicalBiasMean = -0.012,
                                historicalBiasSd = 0.03,
                                sampleCountUsed = 11,
                            ),
                            PollsterBiasPrior(
                                pollster = "Borge y Asociados",
                                historicalBiasMean = 0.005,
                                historicalBiasSd = 0.05,
                                sampleCountUsed = 4,
                            ),
                        ),
                    fundamentalsFeatures =
                        listOf(
                            "incumbent_party",
                            "gdp_growth_yoy",
                            "inflation_yoy",
                            "remittance_growth_yoy",
                            "homicide_rate_yoy",
                            "sentiment_trend_30d",
                        ),
                    sentimentAsModelledInput = false,
                    calibrationThresholds =
                        CalibrationThresholds(
                            c180PctCoverage = 0.80,
                            c295PctCoverage = 0.95,
                            c3Top3MaePp = 5.0,
                        ),
                ),
            longFormUrl = "https://polityk.gt/methodology#presidential-0.1.0",
        )
}
