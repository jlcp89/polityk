@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package gt.polityk.forecast.ui.tabs

import app.cash.turbine.test
import gt.polityk.forecast.data.repo.TabAvailability
import gt.polityk.forecast.data.repo.TabAvailabilityRepository
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
import org.junit.Before
import org.junit.Test

class TabAvailabilityViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setMain() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun resetMain() {
        Dispatchers.resetMain()
    }

    @Test
    fun `emits availability returned by the repository`() =
        runTest {
            val repo = mockk<TabAvailabilityRepository>()
            coEvery { repo.availability() } returns
                TabAvailability(
                    congressAvailable = false,
                    municipalAvailable = true,
                )

            val viewModel = TabAvailabilityViewModel(repo)

            viewModel.state.test {
                // Initial state is "show everything" so the bar is never empty on cold start.
                assertEquals(
                    TabAvailability(congressAvailable = true, municipalAvailable = true),
                    awaitItem(),
                )
                advanceUntilIdle()
                assertEquals(
                    TabAvailability(congressAvailable = false, municipalAvailable = true),
                    awaitItem(),
                )
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `repository failure leaves the default optimistic state intact`() =
        runTest {
            val repo = mockk<TabAvailabilityRepository>()
            coEvery { repo.availability() } throws RuntimeException("offline")

            val viewModel = TabAvailabilityViewModel(repo)

            viewModel.state.test {
                assertEquals(
                    TabAvailability(congressAvailable = true, municipalAvailable = true),
                    awaitItem(),
                )
                advanceUntilIdle()
                // No second emission: the optimistic default is preserved.
                expectNoEvents()
                cancelAndIgnoreRemainingEvents()
            }
        }
}
