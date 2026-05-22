package gt.polityk.forecast.ui.methodology

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import gt.polityk.forecast.data.repo.MethodologyRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MethodologyViewModel
    @Inject
    constructor(
        private val repository: MethodologyRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow<MethodologyUiState>(MethodologyUiState.Loading)
        val state: StateFlow<MethodologyUiState> = _state.asStateFlow()

        init {
            load()
        }

        fun load() {
            _state.value = MethodologyUiState.Loading
            viewModelScope.launch {
                _state.value =
                    runCatching { repository.fetch() }
                        .fold(
                            onSuccess = { MethodologyUiState.Ready(it) },
                            onFailure = { error ->
                                MethodologyUiState.Error(error.message ?: "unknown error")
                            },
                        )
            }
        }
    }
