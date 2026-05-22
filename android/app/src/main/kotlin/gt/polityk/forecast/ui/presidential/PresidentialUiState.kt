package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.PresidentialPayload

sealed interface PresidentialUiState {
    data object Loading : PresidentialUiState

    data class Ready(val payload: PresidentialPayload) : PresidentialUiState

    data class Error(val message: String) : PresidentialUiState
}
