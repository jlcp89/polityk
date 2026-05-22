package gt.polityk.forecast.data.repo

import android.content.SharedPreferences
import gt.polityk.forecast.data.api.PolitykApi
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset

class TabAvailabilityRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var realApi: PolitykApi

    private val baseInstant: Instant = Instant.parse("2026-05-22T13:00:00Z")
    private val baseClock: Clock = Clock.fixed(baseInstant, ZoneOffset.UTC)

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(OkHttpClient.Builder().build())
                .addConverterFactory(MoshiConverterFactory.create())
                .build()
        realApi = retrofit.create(PolitykApi::class.java)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `cache miss probes both endpoints and writes the result`() =
        runTest {
            val storage = fakePreferences()
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertTrue(availability.congressAvailable)
            assertTrue(availability.municipalAvailable)
            // Cache was populated with both flags + a written-at timestamp.
            assertEquals(true, storage.map[TabAvailabilityRepository.KEY_CONGRESS])
            assertEquals(true, storage.map[TabAvailabilityRepository.KEY_MUNICIPAL])
            assertEquals(
                baseClock.millis(),
                storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS],
            )

            assertEquals("/v1/forecast/congress", server.takeRequest().path)
            assertEquals(
                "/v1/forecast/municipal/${TabAvailabilityRepository.MUNICIPAL_SENTINEL_ID}",
                server.takeRequest().path,
            )
        }

    @Test
    fun `congress 404 hides congress tab and municipal 200 keeps municipal tab`() =
        runTest {
            val storage = fakePreferences()
            server.enqueue(MockResponse().setResponseCode(404))
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertFalse(availability.congressAvailable)
            assertTrue(availability.municipalAvailable)
            assertEquals(false, storage.map[TabAvailabilityRepository.KEY_CONGRESS])
            assertEquals(true, storage.map[TabAvailabilityRepository.KEY_MUNICIPAL])
        }

    @Test
    fun `municipal 404 hides municipal tab and congress 200 keeps congress tab`() =
        runTest {
            val storage = fakePreferences()
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
            server.enqueue(MockResponse().setResponseCode(404))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertTrue(availability.congressAvailable)
            assertFalse(availability.municipalAvailable)
        }

    @Test
    fun `both 404 hides both tabs`() =
        runTest {
            val storage = fakePreferences()
            server.enqueue(MockResponse().setResponseCode(404))
            server.enqueue(MockResponse().setResponseCode(404))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertFalse(availability.congressAvailable)
            assertFalse(availability.municipalAvailable)
        }

    @Test
    fun `cache hit within 24h skips the network`() =
        runTest {
            val storage = fakePreferences()
            // Seed an existing fresh cache: written 1h ago, congress=true, municipal=false.
            val writtenAt = baseInstant.minus(Duration.ofHours(1)).toEpochMilli()
            storage.map[TabAvailabilityRepository.KEY_CONGRESS] = true
            storage.map[TabAvailabilityRepository.KEY_MUNICIPAL] = false
            storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS] = writtenAt

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertTrue(availability.congressAvailable)
            assertFalse(availability.municipalAvailable)
            assertEquals(0, server.requestCount)
        }

    @Test
    fun `cache hit beyond 24h triggers a refresh and overwrites the cache`() =
        runTest {
            val storage = fakePreferences()
            val writtenAt =
                baseInstant
                    .minus(Duration.ofHours(25))
                    .toEpochMilli()
            storage.map[TabAvailabilityRepository.KEY_CONGRESS] = false
            storage.map[TabAvailabilityRepository.KEY_MUNICIPAL] = false
            storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS] = writtenAt

            // The API now says both are live.
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability()

            assertTrue(availability.congressAvailable)
            assertTrue(availability.municipalAvailable)
            assertEquals(2, server.requestCount)
            assertEquals(true, storage.map[TabAvailabilityRepository.KEY_CONGRESS])
            assertEquals(true, storage.map[TabAvailabilityRepository.KEY_MUNICIPAL])
            assertEquals(baseClock.millis(), storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS])
        }

    @Test
    fun `force refresh ignores the cache`() =
        runTest {
            val storage = fakePreferences()
            val writtenAt = baseInstant.minus(Duration.ofMinutes(5)).toEpochMilli()
            storage.map[TabAvailabilityRepository.KEY_CONGRESS] = true
            storage.map[TabAvailabilityRepository.KEY_MUNICIPAL] = true
            storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS] = writtenAt
            server.enqueue(MockResponse().setResponseCode(404))
            server.enqueue(MockResponse().setResponseCode(404))

            val repo = TabAvailabilityRepository(realApi, storage.prefs, baseClock)
            val availability = repo.availability(forceRefresh = true)

            assertFalse(availability.congressAvailable)
            assertFalse(availability.municipalAvailable)
            assertEquals(2, server.requestCount)
        }

    @Test
    fun `network exception leaves cache untouched and defaults to available`() =
        runTest {
            val storage = fakePreferences()
            val api = mockk<PolitykApi>()
            coEvery { api.probeCongress() } throws IOException("dns failed")
            coEvery { api.probeMunicipal(any()) } throws IOException("dns failed")

            val repo = TabAvailabilityRepository(api, storage.prefs, baseClock)
            val availability = repo.availability()

            // Default to visible so the user can at least open the tab.
            assertTrue(availability.congressAvailable)
            assertTrue(availability.municipalAvailable)
            // But do NOT cache the transient failure for 24h.
            assertNull(storage.map[TabAvailabilityRepository.KEY_CONGRESS])
            assertNull(storage.map[TabAvailabilityRepository.KEY_MUNICIPAL])
            assertNull(storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS])
        }

    @Test
    fun `mixed exception and success still leaves cache untouched`() =
        runTest {
            val storage = fakePreferences()
            val api = mockk<PolitykApi>()
            coEvery { api.probeCongress() } returns
                Response.success<okhttp3.ResponseBody>(
                    "{}".toResponseBody("application/json".toMediaType()),
                )
            coEvery { api.probeMunicipal(any()) } throws IOException("nope")

            val repo = TabAvailabilityRepository(api, storage.prefs, baseClock)
            val availability = repo.availability()

            assertTrue(availability.congressAvailable)
            assertTrue(availability.municipalAvailable)
            assertNull(storage.map[TabAvailabilityRepository.KEY_WRITTEN_AT_MS])
        }

    @Test
    fun `availability call routes municipal probe through sentinel id zero`() =
        runTest {
            val storage = fakePreferences()
            val api = mockk<PolitykApi>()
            val captured = slot<Long>()
            coEvery { api.probeCongress() } returns
                Response.success<okhttp3.ResponseBody>(
                    "{}".toResponseBody("application/json".toMediaType()),
                )
            coEvery { api.probeMunicipal(capture(captured)) } returns
                Response.success<okhttp3.ResponseBody>(
                    "{}".toResponseBody("application/json".toMediaType()),
                )

            val repo = TabAvailabilityRepository(api, storage.prefs, baseClock)
            repo.availability()

            assertEquals(TabAvailabilityRepository.MUNICIPAL_SENTINEL_ID, captured.captured)
            coVerify(exactly = 1) { api.probeMunicipal(TabAvailabilityRepository.MUNICIPAL_SENTINEL_ID) }
        }

    // ---- helpers -------------------------------------------------------------

    /**
     * In-memory [SharedPreferences] backed by a [MutableMap]. Only the surface used by
     * [TabAvailabilityRepository] is wired — get/put for [Boolean]/[Long] plus
     * [SharedPreferences.contains] and [SharedPreferences.Editor.apply].
     */
    private class FakePreferences {
        val map: MutableMap<String, Any?> = mutableMapOf()
        val prefs: SharedPreferences

        init {
            val editor = mockk<SharedPreferences.Editor>()
            every { editor.putBoolean(any(), any()) } answers {
                map[firstArg()] = secondArg<Boolean>()
                editor
            }
            every { editor.putLong(any(), any()) } answers {
                map[firstArg()] = secondArg<Long>()
                editor
            }
            every { editor.apply() } returns Unit
            every { editor.commit() } returns true
            every { editor.remove(any()) } answers {
                map.remove(firstArg<String>())
                editor
            }
            every { editor.clear() } answers {
                map.clear()
                editor
            }

            prefs = mockk<SharedPreferences>()
            every { prefs.edit() } returns editor
            every { prefs.contains(any()) } answers { map.containsKey(firstArg<String>()) }
            every { prefs.getLong(any(), any()) } answers {
                (map[firstArg<String>()] as? Long) ?: secondArg<Long>()
            }
            every { prefs.getBoolean(any(), any()) } answers {
                (map[firstArg<String>()] as? Boolean) ?: secondArg<Boolean>()
            }
        }
    }

    private fun fakePreferences(): FakePreferences = FakePreferences()
}
