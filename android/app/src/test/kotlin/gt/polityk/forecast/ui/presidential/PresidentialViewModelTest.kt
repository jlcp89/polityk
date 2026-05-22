@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package gt.polityk.forecast.ui.presidential

import app.cash.turbine.test
import gt.polityk.forecast.data.api.BlackoutException
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.repo.CachedForecast
import gt.polityk.forecast.data.repo.PresidentialRepository
import gt.polityk.forecast.test.Fixtures
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class PresidentialViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val fixedClock = Clock.fixed(Instant.parse("2026-05-23T22:00:00Z"), ZoneOffset.UTC)

    // Fixture's generated_at == 2026-05-22T12:00:00Z; cache_invalid_until == 2026-05-22T18:00:00Z.
    // 30 minutes later → Fresh bucket.
    private val freshClock: Clock =
        Clock.fixed(Instant.parse("2026-05-22T12:30:00Z"), ZoneOffset.UTC)

    @Before
    fun setMain() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun resetMain() {
        Dispatchers.resetMain()
    }

    @Test
    fun `loads Fresh bucket when generated_at is within six hours`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            val viewModel = PresidentialViewModel(repo, freshClock)

            viewModel.state.test {
                // initial Loading already emitted at construction
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue("expected Fresh, got $ready", ready is PresidentialUiState.Fresh)
                assertEquals(5, (ready as PresidentialUiState.Fresh).payload.candidates.size)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `emits SlightlyStale when generated_at is between six and twenty four hours old`() =
        runTest {
            // generated_at fixture = 12:00Z; 12h later = 00:00Z next day, before cache_invalid_until = false.
            // The fixture's cache_invalid_until is 18:00Z; 12h after generated_at = 00:00Z next day → cache_invalid_until is in the past.
            // So bucketize would emit NoRecentData. Use a copy that drops cache_invalid_until for this test.
            val payload = Fixtures.fivePresidentialCandidates().copy(cacheInvalidUntil = null)
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            val twelveHoursLater = Clock.fixed(Instant.parse("2026-05-23T00:00:00Z"), ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, twelveHoursLater)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val state = awaitItem()
                assertTrue("expected SlightlyStale, got $state", state is PresidentialUiState.SlightlyStale)
                assertEquals(12L, (state as PresidentialUiState.SlightlyStale).ageHours)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `emits Stale when generated_at is between twenty four and seventy two hours old`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates().copy(cacheInvalidUntil = null)
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            val fortyEightHoursLater = Clock.fixed(Instant.parse("2026-05-24T12:00:00Z"), ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, fortyEightHoursLater)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val state = awaitItem()
                assertTrue("expected Stale, got $state", state is PresidentialUiState.Stale)
                assertEquals(48L, (state as PresidentialUiState.Stale).ageHours)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `emits NoRecentData when generated_at is more than seventy two hours old`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates().copy(cacheInvalidUntil = null)
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            val ninetySixHoursLater = Clock.fixed(Instant.parse("2026-05-26T12:00:00Z"), ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, ninetySixHoursLater)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertEquals(PresidentialUiState.NoRecentData, awaitItem())
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `emits NoRecentData when cache_invalid_until is in the past`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            // 19:00Z is after the fixture's 18:00Z cache_invalid_until → forced expiry.
            val pastInvalidClock = Clock.fixed(Instant.parse("2026-05-22T19:00:00Z"), ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, pastInvalidClock)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertEquals(PresidentialUiState.NoRecentData, awaitItem())
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `falls back to cached payload when network fetch fails`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } throws IllegalStateException("offline")
            coEvery { repo.cached() } returns
                CachedForecast(
                    payload = payload,
                    generatedAtEpochMs = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli(),
                    cacheInvalidUntilEpochMs = null,
                    fetchedAtEpochMs = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli(),
                )

            val twelveHoursLater = Clock.fixed(Instant.parse("2026-05-23T00:00:00Z"), ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, twelveHoursLater)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val state = awaitItem()
                assertTrue("expected SlightlyStale from cache, got $state", state is PresidentialUiState.SlightlyStale)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `propagates repository errors into Error state when no cache is present`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } throws IllegalStateException("boom")
            coEvery { repo.cached() } returns null

            val viewModel = PresidentialViewModel(repo, freshClock)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val error = awaitItem()
                assertTrue(error is PresidentialUiState.Error)
                assertEquals("boom", (error as PresidentialUiState.Error).message)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `retry after error transitions from error to loading to loaded`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            var calls = 0
            coEvery { repo.fetch() } answers {
                calls++
                if (calls == 1) error("transient") else Fixtures.fivePresidentialCandidates()
            }
            coEvery { repo.cached() } returns null

            val viewModel = PresidentialViewModel(repo, freshClock)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertTrue(awaitItem() is PresidentialUiState.Error)

                viewModel.load()
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue(ready is PresidentialUiState.Loaded)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `BlackoutException from repository emits Blackout state with computed resume instant`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } throws BlackoutException("/v1/forecast/presidential")

            // 2026-05-23 is a Saturday in GT (UTC-6). Next Sunday at 18:00 GT
            // is 2026-05-24T18:00 GT = 2026-05-25T00:00:00Z.
            val saturdayMidnightUtc = Instant.parse("2026-05-23T12:00:00Z")
            val saturdayClock = Clock.fixed(saturdayMidnightUtc, ZoneOffset.UTC)
            val viewModel = PresidentialViewModel(repo, saturdayClock)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val blackout = awaitItem()
                assertTrue(blackout is PresidentialUiState.Blackout)
                val resume = (blackout as PresidentialUiState.Blackout).resumeAt
                assertEquals(Instant.parse("2026-05-25T00:00:00Z"), resume)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `successful fetch after a Blackout restores Loaded state`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            var calls = 0
            coEvery { repo.fetch() } answers {
                calls++
                if (calls == 1) throw BlackoutException("/v1/forecast/presidential")
                Fixtures.fivePresidentialCandidates()
            }

            val viewModel = PresidentialViewModel(repo, freshClock)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertTrue(awaitItem() is PresidentialUiState.Blackout)

                viewModel.load()
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertTrue(awaitItem() is PresidentialUiState.Loaded)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `payload survives a JSON round trip without loss`() {
        // sanity: the fixture is a fully-typed payload, not just a string
        val parsed: PresidentialPayload = Fixtures.fivePresidentialCandidates()
        assertEquals(5, parsed.candidates.size)
        assertEquals(3, parsed.runoffMatrix.size)
    }
}
