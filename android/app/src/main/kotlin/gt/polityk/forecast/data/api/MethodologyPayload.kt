package gt.polityk.forecast.data.api

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * Canonical `/v1/methodology` payload per issue #13 / ADR-014.
 *
 * Never gated by the blackout middleware (the methodology page is always
 * reachable), so the client can fetch it independently of the forecast.
 */
@JsonClass(generateAdapter = true)
data class MethodologyPayload(
    @Json(name = "model_version") val modelVersion: String,
    @Json(name = "generated_at") val generatedAt: String,
    @Json(name = "presidential") val presidential: PresidentialMethodology,
    @Json(name = "long_form_url") val longFormUrl: String,
)

@JsonClass(generateAdapter = true)
data class PresidentialMethodology(
    @Json(name = "pollster_bias_priors") val pollsterBiasPriors: List<PollsterBiasPrior> = emptyList(),
    @Json(name = "fundamentals_features") val fundamentalsFeatures: List<String> = emptyList(),
    @Json(name = "sentiment_as_modelled_input") val sentimentAsModelledInput: Boolean,
    @Json(name = "calibration_thresholds") val calibrationThresholds: CalibrationThresholds? = null,
)

@JsonClass(generateAdapter = true)
data class PollsterBiasPrior(
    @Json(name = "pollster") val pollster: String,
    @Json(name = "historical_bias_mean") val historicalBiasMean: Double,
    @Json(name = "historical_bias_sd") val historicalBiasSd: Double,
    @Json(name = "sample_count_used") val sampleCountUsed: Int,
)

@JsonClass(generateAdapter = true)
data class CalibrationThresholds(
    @Json(name = "c1_80pct_coverage") val c180PctCoverage: Double,
    @Json(name = "c2_95pct_coverage") val c295PctCoverage: Double,
    @Json(name = "c3_top3_mae_pp") val c3Top3MaePp: Double,
)
