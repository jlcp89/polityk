package gt.polityk.forecast.data.repo

/**
 * Snapshot of which tab destinations the Go API is currently serving. Driven by
 * issue #44: a 404 on `/v1/forecast/{race}` means the race-type isn't live yet,
 * so the corresponding tab must be hidden from the bottom navigation.
 *
 * Presidential is always shown — it is the starting destination and its
 * availability is implicit (#39 makes it the always-on screen).
 */
data class TabAvailability(
    val congressAvailable: Boolean,
    val municipalAvailable: Boolean,
)
