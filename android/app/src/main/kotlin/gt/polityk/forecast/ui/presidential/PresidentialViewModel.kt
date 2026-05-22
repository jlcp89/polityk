package gt.polityk.forecast.ui.presidential

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import gt.polityk.forecast.data.repo.PresidentialRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class PresidentialViewModel
    @Inject
    constructor(
        private val repository: PresidentialRepository,
    ) : ViewModel() {
        private val _state = MutableStateFlow<PresidentialUiState>(PresidentialUiState.Loading)
        val state: StateFlow<PresidentialUiState> = _state.asStateFlow()

        init {
            load()
        }

        fun load() {
            _state.value = PresidentialUiState.Loading
            viewModelScope.launch {
                _state.value =
                    runCatching { repository.fetch() }
                        .fold(
                            onSuccess = { PresidentialUiState.Ready(it) },
                            onFailure = { error ->
                                PresidentialUiState.Error(error.message ?: "unknown error")
                            },
                        )
            }
        }
    }
