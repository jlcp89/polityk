package gt.polityk.forecast.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountBalance
import androidx.compose.material.icons.outlined.HowToVote
import androidx.compose.material.icons.outlined.LocationCity
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavController
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import gt.polityk.forecast.R
import gt.polityk.forecast.data.repo.TabAvailability
import gt.polityk.forecast.ui.tabs.TabAvailabilityViewModel

/**
 * Top-level scaffold for the app. Hosts a bottom [NavigationBar] whose items
 * appear or disappear based on the live [TabAvailability] state (issue #44).
 * The Methodology route deliberately lives outside the tab set so its
 * navigation does not show the bar — it is a sub-screen, not a peer.
 */
@Composable
fun PolitykScaffold(viewModel: TabAvailabilityViewModel = hiltViewModel()) {
    val availability by viewModel.state.collectAsStateWithLifecycle()
    PolitykScaffold(availability = availability)
}

@Composable
fun PolitykScaffold(availability: TabAvailability) {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBar = currentRoute == null || currentRoute in PolitykRoutes.TAB_ROUTES

    Scaffold(
        modifier = Modifier.testTag(SCAFFOLD_TEST_TAG),
        bottomBar = {
            if (showBar) {
                PolitykBottomBar(
                    availability = availability,
                    currentRoute = currentRoute,
                    onSelect = { route -> navigateToTab(navController, route) },
                )
            }
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            PolitykNavHost(navController = navController)
        }
    }
}

private fun navigateToTab(
    navController: NavController,
    route: String,
) {
    if (navController.currentDestination?.route == route) return
    navController.navigate(route) {
        popUpTo(navController.graph.findStartDestination().id) {
            saveState = true
        }
        launchSingleTop = true
        restoreState = true
    }
}

@Composable
fun PolitykBottomBar(
    availability: TabAvailability,
    currentRoute: String?,
    onSelect: (String) -> Unit,
) {
    NavigationBar(modifier = Modifier.testTag(BOTTOM_BAR_TEST_TAG)) {
        TabItem(
            route = PolitykRoutes.PRESIDENTIAL,
            currentRoute = currentRoute,
            label = stringResource(R.string.tab_presidential),
            icon = Icons.Outlined.HowToVote,
            tag = TAB_PRESIDENTIAL_TEST_TAG,
            onSelect = onSelect,
        )
        if (availability.congressAvailable) {
            TabItem(
                route = PolitykRoutes.CONGRESS,
                currentRoute = currentRoute,
                label = stringResource(R.string.tab_congress),
                icon = Icons.Outlined.AccountBalance,
                tag = TAB_CONGRESS_TEST_TAG,
                onSelect = onSelect,
            )
        }
        if (availability.municipalAvailable) {
            TabItem(
                route = PolitykRoutes.MUNICIPAL,
                currentRoute = currentRoute,
                label = stringResource(R.string.tab_municipal),
                icon = Icons.Outlined.LocationCity,
                tag = TAB_MUNICIPAL_TEST_TAG,
                onSelect = onSelect,
            )
        }
    }
}

@Composable
private fun RowScope.TabItem(
    route: String,
    currentRoute: String?,
    label: String,
    icon: ImageVector,
    tag: String,
    onSelect: (String) -> Unit,
) {
    NavigationBarItem(
        modifier = Modifier.testTag(tag),
        selected = currentRoute == route,
        onClick = { onSelect(route) },
        icon = { Icon(imageVector = icon, contentDescription = label) },
        label = { Text(text = label) },
    )
}

const val SCAFFOLD_TEST_TAG: String = "polityk-scaffold"
const val BOTTOM_BAR_TEST_TAG: String = "polityk-bottom-bar"
const val TAB_PRESIDENTIAL_TEST_TAG: String = "tab-presidential"
const val TAB_CONGRESS_TEST_TAG: String = "tab-congress"
const val TAB_MUNICIPAL_TEST_TAG: String = "tab-municipal"
