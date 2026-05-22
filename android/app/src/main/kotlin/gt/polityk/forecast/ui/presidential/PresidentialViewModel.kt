package gt.polityk.forecast.ui.presidential

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.repo.CachedForecast
import gt.polityk.forecast.data.repo.PresidentialRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Clock
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
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
                _state.value = computeNextState()
            }
        }

        private suspend fun computeNextState(): PresidentialUiState =
            runCatching { repository.fetch() }
                .fold(
                    onSuccess = { payload -> classifyFreshPayload(payload) },
                    onFailure = { error -> fallbackToCache(error) },
                )

        private fun classifyFreshPayload(payload: PresidentialPayload): PresidentialUiState =
            bucketize(
                payload = payload,
                generatedAtMs = parseIsoToEpochMs(payload.generatedAt),
                cacheInvalidUntilMs = payload.cacheInvalidUntil?.let(::parseIsoToEpochMs),
                nowMs = clock.millis(),
            )

        private suspend fun fallbackToCache(error: Throwable): PresidentialUiState {
            val cached: CachedForecast =
                repository.cached()
                    ?: return PresidentialUiState.Error(error.message ?: UNKNOWN_ERROR)
            return bucketize(
                payload = cached.payload,
                generatedAtMs = cached.generatedAtEpochMs,
                cacheInvalidUntilMs = cached.cacheInvalidUntilEpochMs,
                nowMs = clock.millis(),
            )
        }

        private fun parseIsoToEpochMs(iso: String): Long? =
            try {
                OffsetDateTime.parse(iso).toInstant().toEpochMilli()
            } catch (_: DateTimeParseException) {
                null
            }

        companion object {
            private const val UNKNOWN_ERROR = "unknown error"
        }
    }
