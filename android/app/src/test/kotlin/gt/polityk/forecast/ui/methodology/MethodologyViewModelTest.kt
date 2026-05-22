@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package gt.polityk.forecast.ui.methodology

import app.cash.turbine.test
import gt.polityk.forecast.data.repo.MethodologyRepository
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

class MethodologyViewModelTest {
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
            val payload = Fixtures.methodology()
            val repo = mockk<MethodologyRepository>()
            coEvery { repo.fetch() } returns payload

            val viewModel = MethodologyViewModel(repo)

            viewModel.state.test {
                assertEquals(MethodologyUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue(ready is MethodologyUiState.Ready)
                assertEquals("0.1.0", (ready as MethodologyUiState.Ready).payload.modelVersion)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `propagates repository errors into Error state with message`() =
        runTest {
            val repo = mockk<MethodologyRepository>()
            coEvery { repo.fetch() } throws IllegalStateException("boom")

            val viewModel = MethodologyViewModel(repo)

            viewModel.state.test {
                assertEquals(MethodologyUiState.Loading, awaitItem())
                advanceUntilIdle()
                val error = awaitItem()
                assertTrue(error is MethodologyUiState.Error)
                assertEquals("boom", (error as MethodologyUiState.Error).message)
                cancelAndIgnoreRemainingEvents()
            }
        }

    @Test
    fun `retry after error transitions back through loading to ready`() =
        runTest {
            val repo = mockk<MethodologyRepository>()
            var calls = 0
            coEvery { repo.fetch() } answers {
                calls++
                if (calls == 1) error("transient") else Fixtures.methodology()
            }

            val viewModel = MethodologyViewModel(repo)

            viewModel.state.test {
                assertEquals(MethodologyUiState.Loading, awaitItem())
                advanceUntilIdle()
                assertTrue(awaitItem() is MethodologyUiState.Error)

                viewModel.load()
                assertEquals(MethodologyUiState.Loading, awaitItem())
                advanceUntilIdle()
                val ready = awaitItem()
                assertTrue(ready is MethodologyUiState.Ready)
                cancelAndIgnoreRemainingEvents()
            }
        }
}
