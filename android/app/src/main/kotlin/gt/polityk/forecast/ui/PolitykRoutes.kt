package gt.polityk.forecast.ui

object PolitykRoutes {
    const val PRESIDENTIAL = "presidential"
    const val CONGRESS = "congress"
    const val MUNICIPAL = "municipal"

    const val METHODOLOGY_BASE = "methodology"
    const val METHODOLOGY_ARG_RUN_ID = "runId"

    fun methodology(runId: String?): String {
        if (runId.isNullOrBlank()) return METHODOLOGY_BASE
        return "$METHODOLOGY_BASE?$METHODOLOGY_ARG_RUN_ID=$runId"
    }

    /** Top-level tab destinations — used by [PolitykScaffold] to decide when the bottom bar is visible. */
    val TAB_ROUTES: Set<String> = setOf(PRESIDENTIAL, CONGRESS, MUNICIPAL)
}
