package gt.polityk.forecast.data.repo

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import gt.polityk.forecast.data.api.BlackoutException
import gt.polityk.forecast.data.api.PolitykApi
import gt.polityk.forecast.data.api.PresidentialPayload
import gt.polityk.forecast.data.db.ForecastCacheDao
import gt.polityk.forecast.data.db.ForecastCacheEntity
import gt.polityk.forecast.test.Fixtures
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

class PresidentialRepositoryTest {
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val adapter = moshi.adapter(PresidentialPayload::class.java)
    private val fixedClock = Clock.fixed(Instant.parse("2026-05-22T13:00:00Z"), ZoneOffset.UTC)

    @Test
    fun `fetch returns the API payload and writes the raw JSON to the cache`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>(relaxed = true)
            coEvery { api.getPresidential() } returns payload

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            val captured = slot<ForecastCacheEntity>()
            coEvery { dao.upsert(capture(captured)) } answers { }

            val returned = repo.fetch()

            assertEquals(payload, returned)
            coVerify(exactly = 1) { dao.upsert(any()) }
            val entity = captured.captured
            val expectedGenerated = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli()
            val expectedInvalid = Instant.parse("2026-05-22T18:00:00Z").toEpochMilli()
            assertEquals(PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY, entity.endpointUrl)
            assertEquals(expectedGenerated, entity.generatedAtEpochMs)
            assertEquals(expectedInvalid, entity.cacheInvalidUntilEpochMs)
            assertEquals(fixedClock.millis(), entity.fetchedAtEpochMs)

            // The stored blob must round-trip back into the same payload (issue #42 will read this).
            val rehydrated = adapter.fromJson(entity.payloadJson)
            assertNotNull(rehydrated)
            assertEquals(payload, rehydrated)
        }

    @Test
    fun `fetch returns API payload even if cache write fails`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>()
            coEvery { api.getPresidential() } returns payload
            coEvery { dao.upsert(any()) } throws RuntimeException("disk full")

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)

            // We never want a transient DB error to break the UI fetch.
            val returned = repo.fetch()
            assertEquals(payload, returned)
        }

    @Test
    fun `fetch tolerates a payload without cache_invalid_until`() =
        runTest {
            val source = Fixtures.fivePresidentialCandidates().copy(cacheInvalidUntil = null)
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>(relaxed = true)
            coEvery { api.getPresidential() } returns source

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            val captured = slot<ForecastCacheEntity>()
            coEvery { dao.upsert(capture(captured)) } answers { }

            repo.fetch()

            assertNull(captured.captured.cacheInvalidUntilEpochMs)
        }

    @Test
    fun `fetch records null generated_at when the timestamp is unparseable`() =
        runTest {
            val source = Fixtures.fivePresidentialCandidates().copy(generatedAt = "not-a-date")
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>(relaxed = true)
            coEvery { api.getPresidential() } returns source

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            val captured = slot<ForecastCacheEntity>()
            coEvery { dao.upsert(capture(captured)) } answers { }

            repo.fetch()

            assertNull(captured.captured.generatedAtEpochMs)
        }

    @Test
    fun `cached returns a parsed CachedForecast when the DAO has a row`() =
        runTest {
            val payload = Fixtures.fivePresidentialCandidates()
            val entity =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = adapter.toJson(payload),
                    generatedAtEpochMs = 1_000L,
                    cacheInvalidUntilEpochMs = 2_000L,
                    fetchedAtEpochMs = 1_500L,
                )
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>()
            coEvery { dao.get(PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY) } returns entity

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            val cached = repo.cached()

            assertNotNull(cached)
            assertEquals(payload, cached!!.payload)
            assertEquals(1_000L, cached.generatedAtEpochMs)
            assertEquals(2_000L, cached.cacheInvalidUntilEpochMs)
            assertEquals(1_500L, cached.fetchedAtEpochMs)
        }

    @Test
    fun `cached returns null when the DAO has no row`() =
        runTest {
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>()
            coEvery { dao.get(any()) } returns null

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            assertNull(repo.cached())
        }

    @Test
    fun `cached returns null when the payload blob is corrupt`() =
        runTest {
            val entity =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = "{not valid json",
                    generatedAtEpochMs = 1L,
                    cacheInvalidUntilEpochMs = null,
                    fetchedAtEpochMs = 2L,
                )
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>()
            coEvery { dao.get(any()) } returns entity

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            assertNull(repo.cached())
        }

    @Test
    fun `fetch on BlackoutException wipes the cached endpoint and rethrows`() =
        runTest {
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>(relaxed = true)
            val blackout = BlackoutException(PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY)
            coEvery { api.getPresidential() } throws blackout

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            val thrown =
                assertThrows(BlackoutException::class.java) {
                    kotlinx.coroutines.runBlocking { repo.fetch() }
                }

            assertSame(blackout, thrown)
            coVerify(exactly = 1) { dao.deleteByEndpoint(PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY) }
            coVerify(exactly = 0) { dao.upsert(any()) }
        }

    @Test
    fun `fetch still rethrows BlackoutException even when cache wipe fails`() =
        runTest {
            val api = mockk<PolitykApi>()
            val dao = mockk<ForecastCacheDao>()
            coEvery { api.getPresidential() } throws BlackoutException("/v1/forecast/presidential")
            coEvery { dao.deleteByEndpoint(any()) } throws RuntimeException("disk full")

            val repo = PresidentialRepository(api, dao, adapter, fixedClock)
            assertThrows(BlackoutException::class.java) {
                kotlinx.coroutines.runBlocking { repo.fetch() }
            }
        }

    @Test
    fun `readCacheIfValid returns the entry when cache_invalid_until is in the future`() =
        runTest {
            val dao = mockk<ForecastCacheDao>()
            val futureMs = Instant.parse("2026-05-22T18:00:00Z").toEpochMilli()
            val entry =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = "{}",
                    generatedAtEpochMs = null,
                    cacheInvalidUntilEpochMs = futureMs,
                    fetchedAtEpochMs = 0,
                )
            coEvery { dao.get(any()) } returns entry

            val repo = PresidentialRepository(mockk(), dao, adapter, fixedClock)
            assertEquals(entry, repo.readCacheIfValid())
        }

    @Test
    fun `readCacheIfValid returns null when cache_invalid_until is in the past`() =
        runTest {
            val dao = mockk<ForecastCacheDao>()
            val pastMs = Instant.parse("2026-05-22T12:00:00Z").toEpochMilli()
            val entry =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = "{}",
                    generatedAtEpochMs = null,
                    cacheInvalidUntilEpochMs = pastMs,
                    fetchedAtEpochMs = 0,
                )
            coEvery { dao.get(any()) } returns entry

            val repo = PresidentialRepository(mockk(), dao, adapter, fixedClock)
            assertNull(repo.readCacheIfValid())
        }

    @Test
    fun `readCacheIfValid treats cache_invalid_until equal to now as expired`() =
        runTest {
            val dao = mockk<ForecastCacheDao>()
            val entry =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = "{}",
                    generatedAtEpochMs = null,
                    cacheInvalidUntilEpochMs = fixedClock.millis(),
                    fetchedAtEpochMs = 0,
                )
            coEvery { dao.get(any()) } returns entry

            val repo = PresidentialRepository(mockk(), dao, adapter, fixedClock)
            assertNull(repo.readCacheIfValid())
        }

    @Test
    fun `readCacheIfValid returns the entry when cache_invalid_until is null`() =
        runTest {
            val dao = mockk<ForecastCacheDao>()
            val entry =
                ForecastCacheEntity(
                    endpointUrl = PresidentialRepository.PRESIDENTIAL_ENDPOINT_KEY,
                    payloadJson = "{}",
                    generatedAtEpochMs = null,
                    cacheInvalidUntilEpochMs = null,
                    fetchedAtEpochMs = 0,
                )
            coEvery { dao.get(any()) } returns entry

            val repo = PresidentialRepository(mockk(), dao, adapter, fixedClock)
            assertEquals(entry, repo.readCacheIfValid())
        }

    @Test
    fun `readCacheIfValid returns null when nothing is cached`() =
        runTest {
            val dao = mockk<ForecastCacheDao>()
            coEvery { dao.get(any()) } returns null

            val repo = PresidentialRepository(mockk(), dao, adapter, fixedClock)
            assertNull(repo.readCacheIfValid())
        }
}
