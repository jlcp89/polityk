package gt.polityk.forecast.ui

object PolitykRoutes {
    const val PRESIDENTIAL = "presidential"
    const val METHODOLOGY_BASE = "methodology"
    const val METHODOLOGY_ARG_RUN_ID = "runId"

    fun methodology(runId: String?): String {
        if (runId.isNullOrBlank()) return METHODOLOGY_BASE
        return "$METHODOLOGY_BASE?$METHODOLOGY_ARG_RUN_ID=$runId"
    }
}
