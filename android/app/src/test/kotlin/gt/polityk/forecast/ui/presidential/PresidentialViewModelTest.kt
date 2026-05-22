@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package gt.polityk.forecast.ui.presidential

import app.cash.turbine.test
import gt.polityk.forecast.data.api.PresidentialPayload
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

class PresidentialViewModelTest {
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
    fun `loads ready state from repository fixture`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } returns payload

            val viewModel = PresidentialViewModel(repo)

            viewModel.state.test {
                // initial Loading already emitted at construction
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue(ready is PresidentialUiState.Ready)
                assertEquals(5, (ready as PresidentialUiState.Ready).payload.candidates.size)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `propagates repository errors into Error state with message`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            coEvery { repo.fetch() } throws IllegalStateException("boom")

            val viewModel = PresidentialViewModel(repo)

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
    fun `retry after error transitions from error to loading to ready`() =
        runTest {
            val repo = mockk<PresidentialRepository>()
            var calls = 0
            coEvery { repo.fetch() } answers {
                calls++
                if (calls == 1) error("transient") else Fixtures.fivePresidentialCandidates()
            }

            val viewModel = PresidentialViewModel(repo)

            viewModel.state.test {
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertTrue(awaitItem() is PresidentialUiState.Error)

                viewModel.load()
                assertEquals(PresidentialUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue(ready is PresidentialUiState.Ready)
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
