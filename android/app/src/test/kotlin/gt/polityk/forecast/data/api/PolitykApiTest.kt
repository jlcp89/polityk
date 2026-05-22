package gt.polityk.forecast.data.api

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import gt.polityk.forecast.test.Fixtures
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory

class PolitykApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PolitykApi

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(OkHttpClient.Builder().build())
                .addConverterFactory(MoshiConverterFactory.create(moshi))
                .build()
        api = retrofit.create(PolitykApi::class.java)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `presidential payload parses ADR-014 fixture with five candidates`() =
        runTest {
            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setHeader("Content-Type", "application/json; charset=utf-8")
                    .setBody(Fixtures.fivePresidentialCandidatesJson()),
            )

            val payload = api.getPresidential()

            assertEquals("00000000-0000-0000-0000-000000000001", payload.runId)
            assertEquals("0.1.0-test", payload.modelVersion)
            assertEquals("presidential", payload.race.type)
            assertEquals(2027, payload.race.cycle)
            assertEquals(1, payload.race.round)
            assertEquals(5, payload.candidates.size)

            val arevalo = payload.candidates.first { it.candidateId == 42L }
            assertEquals("Bernardo Arévalo", arevalo.name)
            assertEquals("Q123", arevalo.wikidataQid)
            assertEquals(0.23, arevalo.voteShare.p50, 1e-9)
            assertEquals(0.62, arevalo.qualifiesForRunoffProbability, 1e-9)

            // wikidata_qid: null parses to a null Kotlin field
            val mulet = payload.candidates.first { it.candidateId == 23L }
            assertNull(mulet.wikidataQid)

            assertEquals(3, payload.runoffMatrix.size)
            assertEquals(0, payload.interventionsApplied.size)
            assertEquals("2026-05-22T18:00:00Z", payload.cacheInvalidUntil)

            val requested = server.takeRequest()
            assertEquals("/v1/forecast/presidential", requested.path)
        }

    @Test
    fun `omitting optional fields still parses`() =
        runTest {
            // intervention array + cache_invalid_until are both optional
            val minimal =
                """
                {
                  "run_id": "x",
                  "model_version": "0.1.0",
                  "generated_at": "2026-05-22T12:00:00Z",
                  "race": {"type": "presidential", "cycle": 2027, "round": 1},
                  "candidates": [],
                  "runoff_matrix": [],
                  "methodology_url": "https://polityk.gt/m"
                }
                """.trimIndent()
            server.enqueue(MockResponse().setResponseCode(200).setBody(minimal))

            val payload = api.getPresidential()

            assertEquals(0, payload.candidates.size)
            assertEquals(0, payload.interventionsApplied.size)
            assertNull(payload.cacheInvalidUntil)
        }
}
