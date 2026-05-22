package gt.polityk.forecast.data.api

import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Path

interface PolitykApi {
    @GET("v1/forecast/presidential")
    suspend fun getPresidential(): PresidentialPayload

    @GET("v1/methodology")
    suspend fun getMethodology(): MethodologyPayload

    /**
     * Status-only probe for the congress race. Issue #44.
     *
     * Returns [Response<ResponseBody>] so the caller inspects [Response.code] without
     * forcing Moshi to materialise the (potentially large) body — and so 404 is a
     * normal terminal state, not a thrown `HttpException`.
     */
    @GET("v1/forecast/congress")
    suspend fun probeCongress(): Response<ResponseBody>

    /**
     * Status-only probe for the municipal race. The sentinel id `0` is reserved by
     * the API (#12) to mean "any municipality" and therefore tells the client
     * whether the race-type is live at all. Returns [Response<ResponseBody>] for
     * the same reason as [probeCongress].
     */
    @GET("v1/forecast/municipal/{id}")
    suspend fun probeMunicipal(
        @Path("id") municipalityId: Long,
    ): Response<ResponseBody>
}
