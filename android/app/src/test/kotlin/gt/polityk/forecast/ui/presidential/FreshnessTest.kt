package gt.polityk.forecast.ui.presidential

import gt.polityk.forecast.test.Fixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Pure-function tests for [bucketize] — covers all four ADR-018 buckets plus
 * the cache_invalid_until edge case. These tests do not touch a Clock or DAO.
 */
class FreshnessTest {
    private val payload = Fixtures.fivePresidentialCandidates()
    private val generated = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli()

    @Test
    fun `boundary at exactly six hours is Fresh`() {
        val now = generated + hoursMs(6)
        val state = bucketize(payload, generated, null, now)
        assertTrue("expected Fresh, got $state", state is PresidentialUiState.Fresh)
        assertEquals(6L, (state as PresidentialUiState.Fresh).ageHours)
    }

    @Test
    fun `one hour old is Fresh`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(1))
        assertTrue(state is PresidentialUiState.Fresh)
    }

    @Test
    fun `seven hours old is SlightlyStale`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(7))
        assertTrue(state is PresidentialUiState.SlightlyStale)
        assertEquals(7L, (state as PresidentialUiState.SlightlyStale).ageHours)
    }

    @Test
    fun `boundary at exactly twenty four hours is SlightlyStale`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(24))
        assertTrue(state is PresidentialUiState.SlightlyStale)
    }

    @Test
    fun `twenty five hours old is Stale`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(25))
        assertTrue(state is PresidentialUiState.Stale)
        assertEquals(25L, (state as PresidentialUiState.Stale).ageHours)
    }

    @Test
    fun `boundary at exactly seventy two hours is Stale`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(72))
        assertTrue(state is PresidentialUiState.Stale)
    }

    @Test
    fun `seventy three hours old is NoRecentData`() {
        val state = bucketize(payload, generated, null, generated + hoursMs(73))
        assertEquals(PresidentialUiState.NoRecentData, state)
    }

    @Test
    fun `cache_invalid_until in the past forces NoRecentData`() {
        val pastInvalid = generated + hoursMs(1) // invalidated just one hour after generation
        val now = generated + hoursMs(2)
        val state = bucketize(payload, generated, pastInvalid, now)
        assertEquals(PresidentialUiState.NoRecentData, state)
    }

    @Test
    fun `cache_invalid_until equal to now forces NoRecentData`() {
        val invalidAt = generated + hoursMs(1)
        val state = bucketize(payload, generated, invalidAt, invalidAt)
        assertEquals(PresidentialUiState.NoRecentData, state)
    }

    @Test
    fun `cache_invalid_until in the future leaves bucket to age`() {
        val futureInvalid = generated + hoursMs(48)
        val state = bucketize(payload, generated, futureInvalid, generated + hoursMs(2))
        assertTrue(state is PresidentialUiState.Fresh)
    }

    @Test
    fun `unparseable generated_at is NoRecentData`() {
        val state = bucketize(payload, null, null, generated + hoursMs(1))
        assertEquals(PresidentialUiState.NoRecentData, state)
    }

    @Test
    fun `generated_at in the future is clamped to Fresh with age zero`() {
        val now = generated - hoursMs(2)
        val state = bucketize(payload, generated, null, now)
        assertTrue(state is PresidentialUiState.Fresh)
        assertEquals(0L, (state as PresidentialUiState.Fresh).ageHours)
    }

    private fun hoursMs(h: Long): Long = h * 60L * 60L * 1000L
}
