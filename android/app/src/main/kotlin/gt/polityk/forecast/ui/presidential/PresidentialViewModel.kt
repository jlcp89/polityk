package gt.polityk.forecast.ui.presidential

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import gt.polityk.forecast.data.api.BlackoutException
import gt.polityk.forecast.data.repo.PresidentialRepository
import gt.polityk.forecast.ui.blackout.BlackoutResumeCalculator
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Clock
import javax.inject.Inject

@HiltViewModel
class PresidentialViewModel
    @Inject
    constructor(
        private val repository: PresidentialRepository,
        private val clock: Clock,
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
                    try {
                        PresidentialUiState.Ready(repository.fetch())
                    } catch (_: BlackoutException) {
                        PresidentialUiState.Blackout(BlackoutResumeCalculator.nextResumeInstant(clock))
                    } catch (error: Exception) {
                        PresidentialUiState.Error(error.message ?: "unknown error")
                    }
            }
        }
    }
