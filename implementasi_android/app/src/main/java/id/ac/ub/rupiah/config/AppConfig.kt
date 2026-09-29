package id.ac.ub.rupiah.config

import android.content.Context
import org.json.JSONObject
import java.security.MessageDigest
import kotlin.math.abs

data class AppConfig(
    val raw: String
) {

    private val json = JSONObject(raw)

    val schemaVersion = json.getInt("schema_version")
    val status = json.getString("status")
    val revision = json.getString("revision")
    val fps = json.getInt("analysis_fps")
    val threads = json.getInt("threads")
    val roiFraction = json.getDouble("roi_width_fraction").toFloat()
    val roiAspect = json.getDouble("roi_aspect_ratio").toFloat()
    val roiHeightCap = json.getDouble("roi_height_cap_fraction").toFloat()
    val blurMin = json.getDouble("blur_variance_min")
    val lumaMin = json.getDouble("luma_min")
    val lumaMax = json.getDouble("luma_max")
    val threshold = json.getDouble("confidence_threshold").toFloat()
    val windowMs = json.getLong("temporal_window_ms")
    val minimumResults = json.getInt("minimum_results")
    val clahe = json.getBoolean("clahe_enabled")
    val clipLimit = nullableDouble("clahe_clip_limit")
    val grid = nullableInt("clahe_grid")
    val yuvRange = json.getString("yuv_range")
    val limitedYuv = yuvRange == "limited_bt601"
    val logging = json.getBoolean("log_enabled")
    val postInferenceStatus = json.getString("postinference_status")
    val staticQualityConfigAsset =
        json.optString("static_quality_config_asset", "")
            .ifBlank { null }
    val staticQualityLockAsset =
        json.optString("static_quality_lock_asset", "")
            .ifBlank { null }
    val staticQualityLockSha256 =
        json.optString("static_quality_lock_sha256", "")
            .ifBlank { null }

    init {
        require(schemaVersion == 2)

        require(
            status in setOf(
                "development_uncalibrated",
                "static_quality_calibrated_postinfer_pending",
                "calibrated"
            )
        )

        require(revision.isNotBlank())

        require(
            fps in 1..5 &&
                    threads in 1..4
        )

        require(
            roiFraction in 0.5f..0.95f &&
                    roiAspect in 1f..4f &&
                    roiHeightCap in 0.5f..1f
        )

        require(
            blurMin.isFinite() &&
                    blurMin >= 0
        )

        require(
            lumaMin.isFinite() &&
                    lumaMax.isFinite() &&
                    lumaMin >= 0 &&
                    lumaMax <= 255 &&
                    lumaMin < lumaMax
        )

        require(
            threshold in 0.5f..0.95f &&
                    windowMs in 1000L..2000L &&
                    minimumResults >= 3
        )

        if (clahe) {
            require(
                clipLimit != null &&
                        clipLimit in 1.5..2.5 &&
                        grid != null &&
                        grid in setOf(4, 8)
            )
        } else {
            require(
                clipLimit == null || clipLimit in 1.5..2.5
            )

            require(
                grid == null || grid in setOf(4, 8)
            )
        }

        require(
            yuvRange in setOf(
                "limited_bt601",
                "full_bt601"
            )
        )

        require(
            postInferenceStatus in setOf(
                "development_pending_5_7_3",
                "calibrated"
            )
        )

        if (status != "development_uncalibrated") {
            require(
                staticQualityConfigAsset != null &&
                        staticQualityLockAsset != null &&
                        staticQualityLockSha256
                            ?.matches(Regex("[a-f0-9]{64}")) == true
            )
        }
    }

    private fun nullableDouble(name: String): Double? =
        if (
            !json.has(name) ||
            json.isNull(name)
        ) {
            null
        } else {
            json.getDouble(name)
        }

    private fun nullableInt(name: String): Int? =
        if (
            !json.has(name) ||
            json.isNull(name)
        ) {
            null
        } else {
            json.getInt(name)
        }

    private fun verifyStaticQualityEvidence(context: Context) {
        if (status == "development_uncalibrated") return

        val lockAsset =
            requireNotNull(staticQualityLockAsset)

        val configAsset =
            requireNotNull(staticQualityConfigAsset)

        val expectedLockHash =
            requireNotNull(staticQualityLockSha256)

        val lockBytes =
            context.assets
                .open(lockAsset)
                .use {
                    it.readBytes()
                }

        check(sha256(lockBytes) == expectedLockHash) {
            "Integritas bukti kalibrasi kualitas statis berubah"
        }

        val lock =
            JSONObject(
                String(
                    lockBytes,
                    Charsets.UTF_8
                )
            )

        check(
            lock.getString("status") ==
                    "static_quality_config_locked"
        )

        val configBytes =
            context.assets
                .open(configAsset)
                .use {
                    it.readBytes()
                }

        val expectedConfigHash =
            lock.getJSONObject("output_sha256")
                .getString("static_quality_config.json")

        check(sha256(configBytes) == expectedConfigHash) {
            "Integritas konfigurasi kualitas statis berubah"
        }

        val evidence =
            JSONObject(
                String(
                    configBytes,
                    Charsets.UTF_8
                )
            )

        val selected =
            lock.getJSONObject(
                "selected_values"
            )

        checkClose(
            json.getDouble("roi_width_fraction"),
            selected.getDouble("roi_width_fraction"),
            "roi_width_fraction"
        )

        checkClose(
            json.getDouble("roi_aspect_ratio"),
            selected.getDouble("roi_aspect_ratio"),
            "roi_aspect_ratio"
        )

        checkClose(
            json.getDouble("roi_height_cap_fraction"),
            selected.getDouble("roi_height_cap_fraction"),
            "roi_height_cap_fraction"
        )

        checkClose(
            blurMin,
            selected.getDouble("blur_variance_min"),
            "blur_variance_min"
        )

        checkClose(
            lumaMin,
            selected.getDouble("luma_min"),
            "luma_min"
        )

        checkClose(
            lumaMax,
            selected.getDouble("luma_max"),
            "luma_max"
        )

        check(
            clahe == selected.getBoolean("clahe_enabled")
        ) {
            "clahe_enabled tidak sesuai bukti kalibrasi"
        }

        checkClose(
            json.getDouble("roi_width_fraction"),
            evidence.getDouble("roi_width_fraction"),
            "roi_width_fraction evidence"
        )

        checkClose(
            json.getDouble("roi_aspect_ratio"),
            evidence.getDouble("roi_aspect_ratio"),
            "roi_aspect_ratio evidence"
        )

        checkClose(
            json.getDouble("roi_height_cap_fraction"),
            evidence.getDouble("roi_height_cap_fraction"),
            "roi_height_cap_fraction evidence"
        )

        checkClose(
            blurMin,
            evidence.getDouble("blur_variance_min"),
            "blur_variance_min evidence"
        )

        checkClose(
            lumaMin,
            evidence.getDouble("luma_min"),
            "luma_min evidence"
        )

        checkClose(
            lumaMax,
            evidence.getDouble("luma_max"),
            "luma_max evidence"
        )

        check(
            clahe == evidence.getBoolean("clahe_enabled")
        ) {
            "clahe_enabled tidak sesuai konfigurasi kalibrasi"
        }

        check(
            yuvRange == evidence.getString("yuv_range")
        ) {
            "yuv_range tidak sesuai konfigurasi kalibrasi"
        }
    }

    private fun checkClose(
        actual: Double,
        expected: Double,
        name: String
    ) {
        check(abs(actual - expected) <= 1e-9) {
            "$name tidak sesuai bukti kalibrasi"
        }
    }

    companion object {
        fun load(context: Context): AppConfig {
            val config =
                AppConfig(
                    context.assets
                        .open("app_config.json")
                        .bufferedReader()
                        .use {
                            it.readText()
                        }
                )

            config.verifyStaticQualityEvidence(context)

            return config
        }

        private fun sha256(bytes: ByteArray) =
            MessageDigest
                .getInstance("SHA-256")
                .digest(bytes)
                .joinToString("") {
                    "%02x".format(
                        it.toInt() and 255
                    )
                }
    }
}
