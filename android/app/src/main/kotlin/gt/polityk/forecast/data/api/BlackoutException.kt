package gt.polityk.forecast.data.api

import java.io.IOException

/**
 * Thrown by [BlackoutInterceptor] when the API returns HTTP 503 on any
 * forecast endpoint, signalling the legal electoral silence window
 * (expediente 1699-2018, ADR-003). Extends [IOException] so it propagates
 * cleanly through Retrofit suspend functions without being wrapped in
 * `HttpException`.
 *
 * `endpointPath` identifies which cached payload must be invalidated by
 * the repository layer.
 */
class BlackoutException(val endpointPath: String) : IOException("blackout 503 on $endpointPath")
