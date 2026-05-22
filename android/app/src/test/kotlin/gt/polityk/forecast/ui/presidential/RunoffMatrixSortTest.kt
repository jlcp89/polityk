package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.data.api.RunoffPair
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RunoffMatrixSortTest {
    @Test
    fun sorts_by_pair_probability_descending_and_caps_to_five() {
        val pairs =
            listOf(
                RunoffPair(1, 2, 0.05, 0.5),
                RunoffPair(1, 3, 0.30, 0.5),
                RunoffPair(2, 3, 0.10, 0.5),
                RunoffPair(1, 4, 0.25, 0.5),
                RunoffPair(2, 4, 0.15, 0.5),
                RunoffPair(3, 4, 0.20, 0.5),
                RunoffPair(1, 5, 0.08, 0.5),
            )

        val top = topRunoffPairs(pairs)

        assertEquals(5, top.size)
        assertEquals(listOf(0.30, 0.25, 0.20, 0.15, 0.10), top.map { it.pairProbability })
    }

    @Test
    fun returns_empty_when_input_empty() {
        assertTrue(topRunoffPairs(emptyList()).isEmpty())
    }

    @Test
    fun returns_all_when_fewer_than_five() {
        val pairs =
            listOf(
                RunoffPair(1, 2, 0.30, 0.5),
                RunoffPair(1, 3, 0.20, 0.5),
            )

        val top = topRunoffPairs(pairs)

        assertEquals(2, top.size)
        assertEquals(listOf(0.30, 0.20), top.map { it.pairProbability })
    }

    @Test
    fun preserves_input_order_among_equal_probabilities() {
        val pairs =
            listOf(
                RunoffPair(1, 2, 0.20, 0.5),
                RunoffPair(3, 4, 0.20, 0.5),
                RunoffPair(5, 6, 0.30, 0.5),
            )

        val top = topRunoffPairs(pairs)

        assertEquals(listOf(5L, 1L, 3L), top.map { it.candidateAId })
    }

    @Test
    fun respects_custom_max_parameter() {
        val pairs =
            listOf(
                RunoffPair(1, 2, 0.30, 0.5),
                RunoffPair(1, 3, 0.20, 0.5),
                RunoffPair(2, 3, 0.10, 0.5),
            )

        assertEquals(1, topRunoffPairs(pairs, max = 1).size)
        assertEquals(0.30, topRunoffPairs(pairs, max = 1).first().pairProbability, 1e-9)
    }
}
