package gt.polityk.forecast.data.api

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test

class BlackoutInterceptorTest {
    private lateinit var server: MockWebServer
    private lateinit var client: OkHttpClient

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        client = OkHttpClient.Builder().addInterceptor(BlackoutInterceptor()).build()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `503 on forecast path throws BlackoutException with the endpoint path`() {
        server.enqueue(MockResponse().setResponseCode(503).setBody("ignored body"))
        val request = Request.Builder().url(server.url("/v1/forecast/presidential")).build()

        val thrown =
            assertThrows(BlackoutException::class.java) {
                client.newCall(request).execute()
            }
        assertEquals("/v1/forecast/presidential", thrown.endpointPath)
    }

    @Test
    fun `503 on non-forecast path passes through unchanged`() {
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
        val request = Request.Builder().url(server.url("/v1/methodology")).build()

        client.newCall(request).execute().use { response ->
            assertEquals(503, response.code)
        }
    }

    @Test
    fun `200 on forecast path passes through unchanged`() {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val request = Request.Builder().url(server.url("/v1/forecast/presidential")).build()

        client.newCall(request).execute().use { response ->
            assertEquals(200, response.code)
        }
    }

    @Test
    fun `404 on forecast path passes through unchanged`() {
        server.enqueue(MockResponse().setResponseCode(404))
        val request = Request.Builder().url(server.url("/v1/forecast/congress")).build()

        client.newCall(request).execute().use { response ->
            assertEquals(404, response.code)
        }
    }
}
