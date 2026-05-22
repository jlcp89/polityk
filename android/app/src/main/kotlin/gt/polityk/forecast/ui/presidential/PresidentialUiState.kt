package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.PresidentialPayload
import java.time.Instant

sealed interface PresidentialUiState {
    data object Loading : PresidentialUiState

    data class Ready(val payload: PresidentialPayload) : PresidentialUiState

    data class Error(val message: String) : PresidentialUiState

    /**
     * Legal silence (expediente 1699-2018): API returned HTTP 503 on a
     * forecast endpoint. Cached payload has been wiped. The splash text
     * lives in-app strings; the API response body is not trusted.
     */
    data class Blackout(val resumeAt: Instant) : PresidentialUiState
}
