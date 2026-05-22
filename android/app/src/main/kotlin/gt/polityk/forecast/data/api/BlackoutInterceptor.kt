package gt.polityk.forecast.data.api

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject

/**
 * Inspects every response under the forecast path prefix and, on HTTP 503,
 * throws a typed [BlackoutException] so the repository layer can wipe the
 * cache and the ViewModel can emit the `Blackout` UI state.
 *
 * The 503 body is closed but never read — the splash text lives in-app
 * strings per ADR-014, never sourced from the response body.
 */
class BlackoutInterceptor
    @Inject
    constructor() : Interceptor {
        override fun intercept(chain: Interceptor.Chain): Response {
            val request = chain.request()
            val response = chain.proceed(request)
            val path = request.url.encodedPath
            if (response.code == BLACKOUT_STATUS && path.startsWith(FORECAST_PATH_PREFIX)) {
                response.close()
                throw BlackoutException(path)
            }
            return response
        }

        companion object {
            const val BLACKOUT_STATUS: Int = 503
            const val FORECAST_PATH_PREFIX: String = "/v1/forecast/"
        }
    }
