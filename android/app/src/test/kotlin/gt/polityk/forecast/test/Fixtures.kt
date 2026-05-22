package gt.polityk.forecast.test

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import gt.polityk.forecast.data.api.PresidentialPayload

object Fixtures {
    private const val FIXTURE_PATH = "fixtures/presidential_five_candidates.json"

    fun fivePresidentialCandidatesJson(): String {
        val stream =
            checkNotNull(javaClass.classLoader?.getResourceAsStream(FIXTURE_PATH)) {
                "Missing test resource: $FIXTURE_PATH"
            }
        return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
    }

    fun fivePresidentialCandidates(): PresidentialPayload {
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val adapter = moshi.adapter(PresidentialPayload::class.java)
        return requireNotNull(adapter.fromJson(fivePresidentialCandidatesJson()))
    }
}
