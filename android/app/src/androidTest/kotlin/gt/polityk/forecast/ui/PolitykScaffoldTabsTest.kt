package gt.polityk.forecast.ui

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import gt.polityk.forecast.data.repo.TabAvailability
import gt.polityk.forecast.ui.theme.PolitykTheme
import org.junit.Rule
import org.junit.Test

/**
 * Compose UI tests for issue #44 acceptance criterion: "Compose UI test covers
 * all four combinations (both 404, both 200, mixed)." Each test renders
 * [PolitykBottomBar] with a fixed [TabAvailability] and asserts the right tabs
 * are visible. Presidential is always present; congress and municipal toggle
 * with the corresponding availability flag.
 *
 * The bar is tested in isolation (rather than through the full [PolitykScaffold]
 * + NavHost stack) because the scaffold instantiates Hilt-injected ViewModels
 * for the presidential route and would otherwise pull in the whole DI graph.
 *
 * Deferred — runs on emulator via `./gradlew connectedAndroidTest`.
 */
class PolitykScaffoldTabsTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun both_endpoints_return_200_shows_all_three_tabs() {
        render(TabAvailability(congressAvailable = true, municipalAvailable = true))

        composeRule.onNodeWithTag(TAB_PRESIDENTIAL_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_CONGRESS_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_MUNICIPAL_TEST_TAG).assertIsDisplayed()
    }

    @Test
    fun both_endpoints_return_404_hides_both_extra_tabs() {
        render(TabAvailability(congressAvailable = false, municipalAvailable = false))

        composeRule.onNodeWithTag(TAB_PRESIDENTIAL_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_CONGRESS_TEST_TAG).assertDoesNotExist()
        composeRule.onNodeWithTag(TAB_MUNICIPAL_TEST_TAG).assertDoesNotExist()
    }

    @Test
    fun congress_200_municipal_404_hides_only_municipal() {
        render(TabAvailability(congressAvailable = true, municipalAvailable = false))

        composeRule.onNodeWithTag(TAB_PRESIDENTIAL_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_CONGRESS_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_MUNICIPAL_TEST_TAG).assertDoesNotExist()
    }

    @Test
    fun congress_404_municipal_200_hides_only_congress() {
        render(TabAvailability(congressAvailable = false, municipalAvailable = true))

        composeRule.onNodeWithTag(TAB_PRESIDENTIAL_TEST_TAG).assertIsDisplayed()
        composeRule.onNodeWithTag(TAB_CONGRESS_TEST_TAG).assertDoesNotExist()
        composeRule.onNodeWithTag(TAB_MUNICIPAL_TEST_TAG).assertIsDisplayed()
    }

    private fun render(availability: TabAvailability) {
        composeRule.setContent {
            PolitykTheme {
                PolitykBottomBar(
                    availability = availability,
                    currentRoute = PolitykRoutes.PRESIDENTIAL,
                    onSelect = {},
                )
            }
        }
    }
}
