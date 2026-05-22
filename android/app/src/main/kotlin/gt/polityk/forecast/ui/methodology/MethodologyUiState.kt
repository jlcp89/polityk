package gt.polityk.forecast.ui.methodology

import gt.polityk.forecast.data.api.MethodologyPayload

sealed interface MethodologyUiState {
    data object Loading : MethodologyUiState

    data class Ready(val payload: MethodologyPayload) : MethodologyUiState

    data class Error(val message: String) : MethodologyUiState
}
