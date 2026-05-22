package gt.polityk.forecast.data.repo

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import gt.polityk.forecast.data.api.PolitykApi
import gt.polityk.forecast.test.Fixtures
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory

class MethodologyRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var repository: MethodologyRepository

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
        val api = retrofit.create(PolitykApi::class.java)
        repository = MethodologyRepository(api)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `fetch returns parsed methodology payload`() =
        runTest {
            server.enqueue(MockResponse().setResponseCode(200).setBody(Fixtures.methodologyJson()))

            val payload = repository.fetch()

            assertEquals("0.1.0", payload.modelVersion)
            assertEquals(3, payload.presidential.pollsterBiasPriors.size)
            assertEquals("/v1/methodology", server.takeRequest().path)
        }

    @Test(expected = retrofit2.HttpException::class)
    fun `fetch propagates http errors`() =
        runTest {
            server.enqueue(MockResponse().setResponseCode(500))

            repository.fetch()
        }
}
