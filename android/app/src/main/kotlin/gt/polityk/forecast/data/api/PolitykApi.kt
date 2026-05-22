package gt.polityk.forecast.data.api

import retrofit2.http.GET

interface PolitykApi {
    @GET("v1/forecast/presidential")
    suspend fun getPresidential(): PresidentialPayload

    @GET("v1/methodology")
    suspend fun getMethodology(): MethodologyPayload
}
