package gt.polityk.forecast.ui.tabs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import gt.polityk.forecast.data.repo.TabAvailability
import gt.polityk.forecast.data.repo.TabAvailabilityRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Top-level Hilt ViewModel that surfaces [TabAvailability] for the bottom
 * navigation. Defaults to showing all tabs until the first probe completes —
 * users see something sensible during the network round-trip, and a 404 only
 * removes a tab if the API actually answered with one.
 */
@HiltViewModel
class TabAvailabilityViewModel
    @Inject
    constructor(
        private val repository: TabAvailabilityRepository,
    ) : ViewModel() {
        private val _state =
            MutableStateFlow(
                TabAvailability(congressAvailable = true, municipalAvailable = true),
            )
        val state: StateFlow<TabAvailability> = _state.asStateFlow()

        init {
            refresh()
        }

        fun refresh() {
            viewModelScope.launch {
                runCatching { repository.availability() }
                    .onSuccess { _state.value = it }
            }
        }
    }
