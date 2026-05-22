package gt.polityk.forecast.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import gt.polityk.forecast.ui.congress.CongressRoute
import gt.polityk.forecast.ui.methodology.MethodologyRoute
import gt.polityk.forecast.ui.municipal.MunicipalRoute
import gt.polityk.forecast.ui.presidential.PresidentialRoute
import gt.polityk.forecast.ui.presidential.PresidentialUiState
import gt.polityk.forecast.ui.presidential.PresidentialViewModel

@Composable
fun PolitykNavHost(navController: NavHostController = rememberNavController()) {
    NavHost(navController = navController, startDestination = PolitykRoutes.PRESIDENTIAL) {
        composable(PolitykRoutes.PRESIDENTIAL) {
            val viewModel: PresidentialViewModel = hiltViewModel()
            val state by viewModel.state.collectAsStateWithLifecycle()
            val runId = (state as? PresidentialUiState.Loaded)?.payload?.runId
            PresidentialRoute(
                viewModel = viewModel,
                onOpenMethodology = {
                    navController.navigate(PolitykRoutes.methodology(runId))
                },
            )
        }
        composable(PolitykRoutes.CONGRESS) { CongressRoute() }
        composable(PolitykRoutes.MUNICIPAL) { MunicipalRoute() }
        composable(
            route = "${PolitykRoutes.METHODOLOGY_BASE}?${PolitykRoutes.METHODOLOGY_ARG_RUN_ID}={${PolitykRoutes.METHODOLOGY_ARG_RUN_ID}}",
            arguments =
                listOf(
                    navArgument(PolitykRoutes.METHODOLOGY_ARG_RUN_ID) {
                        type = NavType.StringType
                        nullable = true
                        defaultValue = null
                    },
                ),
        ) { entry ->
            val runId = entry.arguments?.getString(PolitykRoutes.METHODOLOGY_ARG_RUN_ID)
            MethodologyRoute(
                runIdHint = runId,
                onBack = { navController.popBackStack() },
            )
        }
    }
}
