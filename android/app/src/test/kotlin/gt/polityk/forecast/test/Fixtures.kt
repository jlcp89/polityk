package gt.polityk.forecast.test

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import gt.polityk.forecast.data.api.MethodologyPayload
import gt.polityk.forecast.data.api.PresidentialPayload

object Fixtures {
    private const val PRESIDENTIAL_FIXTURE_PATH = "fixtures/presidential_five_candidates.json"
    private const val METHODOLOGY_FIXTURE_PATH = "fixtures/methodology_v0_1_0.json"

    fun fivePresidentialCandidatesJson(): String = readResource(PRESIDENTIAL_FIXTURE_PATH)

    fun fivePresidentialCandidates(): PresidentialPayload {
        val adapter = moshi().adapter(PresidentialPayload::class.java)
        return requireNotNull(adapter.fromJson(fivePresidentialCandidatesJson()))
    }

    fun methodologyJson(): String = readResource(METHODOLOGY_FIXTURE_PATH)

    fun methodology(): MethodologyPayload {
        val adapter = moshi().adapter(MethodologyPayload::class.java)
        return requireNotNull(adapter.fromJson(methodologyJson()))
    }

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun readResource(path: String): String {
        val stream =
            checkNotNull(javaClass.classLoader?.getResourceAsStream(path)) {
                "Missing test resource: $path"
            }
        return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
    }
}
