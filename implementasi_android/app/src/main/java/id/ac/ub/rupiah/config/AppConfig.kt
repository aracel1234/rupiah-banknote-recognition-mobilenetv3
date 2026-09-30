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
    val clipLimit = nullableDouble(json, "clahe_clip_limit")
    val grid = nullableInt(json, "clahe_grid")
    val yuvRange = json.getString("yuv_range")
    val limitedYuv = yuvRange == "limited_bt601"
    val logging = json.getBoolean("log_enabled")
    val postInferenceStatus = json.getString("postinference_status")

    val staticQualityConfigAsset =
        json.optString(
            "static_quality_config_asset",
            ""
        ).ifBlank { null }

    val staticQualityLockAsset =
        json.optString(
            "static_quality_lock_asset",
            ""
        ).ifBlank { null }

    val staticQualityLockSha256 =
        json.optString(
            "static_quality_lock_sha256",
            ""
        ).ifBlank { null }

    init {
        require(schemaVersion == 2) {
            "schema_version aplikasi harus 2"
        }

        require(
            status == "operational_config_locked"
        ) {
            "Konfigurasi aplikasi belum menggunakan penguncian operasional final"
        }

        require(
            revision == "calib-operational-001"
        ) {
            "Revisi konfigurasi operasional tidak sesuai hasil Subbab 5.7"
        }

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
                    blurMin >= 0.0
        )

        require(
            lumaMin.isFinite() &&
                    lumaMax.isFinite() &&
                    lumaMin >= 0.0 &&
                    lumaMax <= 255.0 &&
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
                clipLimit == null ||
                        clipLimit in 1.5..2.5
            )

            require(
                grid == null ||
                        grid in setOf(4, 8)
            )
        }

        require(
            yuvRange in setOf(
                "limited_bt601",
                "full_bt601"
            )
        )

        require(
            postInferenceStatus ==
                    "calibrated_sequence_locked"
        ) {
            "Konfigurasi pascainferensi belum dikunci"
        }

        require(
            staticQualityConfigAsset != null &&
                    staticQualityLockAsset != null &&
                    staticQualityLockSha256
                        ?.matches(
                            Regex("[a-f0-9]{64}")
                        ) == true
        ) {
            "Referensi bukti kalibrasi kualitas statis tidak lengkap"
        }
    }

    private fun verifyStaticQualityEvidence(
        context: Context
    ) {
        val lockAsset =
            requireNotNull(
                staticQualityLockAsset
            )

        val configAsset =
            requireNotNull(
                staticQualityConfigAsset
            )

        val expectedLockHash =
            requireNotNull(
                staticQualityLockSha256
            )

        val lockBytes =
            context.assets
                .open(lockAsset)
                .use {
                    it.readBytes()
                }

        check(
            sha256(lockBytes) ==
                    expectedLockHash
        ) {
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
        ) {
            "Status lock kualitas statis tidak valid"
        }

        val configBytes =
            context.assets
                .open(configAsset)
                .use {
                    it.readBytes()
                }

        val expectedConfigHash =
            lock.getJSONObject(
                "output_sha256"
            ).getString(
                "static_quality_config.json"
            )

        check(
            sha256(configBytes) ==
                    expectedConfigHash
        ) {
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
            json.getDouble(
                "roi_width_fraction"
            ),
            selected.getDouble(
                "roi_width_fraction"
            ),
            "roi_width_fraction"
        )

        checkClose(
            json.getDouble(
                "roi_aspect_ratio"
            ),
            selected.getDouble(
                "roi_aspect_ratio"
            ),
            "roi_aspect_ratio"
        )

        checkClose(
            json.getDouble(
                "roi_height_cap_fraction"
            ),
            selected.getDouble(
                "roi_height_cap_fraction"
            ),
            "roi_height_cap_fraction"
        )

        checkClose(
            blurMin,
            selected.getDouble(
                "blur_variance_min"
            ),
            "blur_variance_min"
        )

        checkClose(
            lumaMin,
            selected.getDouble(
                "luma_min"
            ),
            "luma_min"
        )

        checkClose(
            lumaMax,
            selected.getDouble(
                "luma_max"
            ),
            "luma_max"
        )

        check(
            clahe ==
                    selected.getBoolean(
                        "clahe_enabled"
                    )
        ) {
            "clahe_enabled tidak sesuai bukti kalibrasi"
        }

        checkClose(
            json.getDouble(
                "roi_width_fraction"
            ),
            evidence.getDouble(
                "roi_width_fraction"
            ),
            "roi_width_fraction evidence"
        )

        checkClose(
            json.getDouble(
                "roi_aspect_ratio"
            ),
            evidence.getDouble(
                "roi_aspect_ratio"
            ),
            "roi_aspect_ratio evidence"
        )

        checkClose(
            json.getDouble(
                "roi_height_cap_fraction"
            ),
            evidence.getDouble(
                "roi_height_cap_fraction"
            ),
            "roi_height_cap_fraction evidence"
        )

        checkClose(
            blurMin,
            evidence.getDouble(
                "blur_variance_min"
            ),
            "blur_variance_min evidence"
        )

        checkClose(
            lumaMin,
            evidence.getDouble(
                "luma_min"
            ),
            "luma_min evidence"
        )

        checkClose(
            lumaMax,
            evidence.getDouble(
                "luma_max"
            ),
            "luma_max evidence"
        )

        check(
            clahe ==
                    evidence.getBoolean(
                        "clahe_enabled"
                    )
        ) {
            "clahe_enabled tidak sesuai konfigurasi kalibrasi"
        }

        check(
            yuvRange ==
                    evidence.getString(
                        "yuv_range"
                    )
        ) {
            "yuv_range tidak sesuai konfigurasi kalibrasi"
        }
    }

    private fun verifyOperationalEvidence(
        context: Context
    ) {
        val lockBytes =
            context.assets
                .open(
                    OPERATIONAL_LOCK_ASSET
                )
                .use {
                    it.readBytes()
                }

        check(
            sha256(lockBytes) ==
                    OPERATIONAL_LOCK_SHA256
        ) {
            "Integritas lock konfigurasi operasional berubah"
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
                    "operational_configuration_locked"
        ) {
            "Status lock konfigurasi operasional tidak valid"
        }

        val dependencies =
            lock.getJSONObject(
                "dependencies"
            )

        check(
            dependencies.getString(
                "static_quality_lock_sha256"
            ) == staticQualityLockSha256
        ) {
            "Lock operasional tidak merujuk bukti kualitas statis yang digunakan aplikasi"
        }

        val outputHashes =
            lock.getJSONObject(
                "output_sha256"
            )

        val expectedAndroidConfigHash =
            outputHashes.getString(
                "android_app_config_final.json"
            )

        check(
            sha256(
                raw.toByteArray(
                    Charsets.UTF_8
                )
            ) == expectedAndroidConfigHash
        ) {
            "app_config.json tidak sama dengan konfigurasi Android final hasil kalibrasi"
        }

        val operationalBytes =
            context.assets
                .open(
                    OPERATIONAL_CONFIG_ASSET
                )
                .use {
                    it.readBytes()
                }

        check(
            sha256(operationalBytes) ==
                    outputHashes.getString(
                        "operational_config.json"
                    )
        ) {
            "Integritas operational_config.json berubah"
        }

        val operational =
            JSONObject(
                String(
                    operationalBytes,
                    Charsets.UTF_8
                )
            )

        check(
            operational.getInt(
                "schema_version"
            ) == 1
        )

        check(
            operational.getString(
                "status"
            ) ==
                    "operational_configuration_calibrated"
        )

        val selected =
            lock.getJSONObject(
                "selected_values"
            )

        check(
            selected.getInt(
                "schema_version"
            ) == 1
        )

        check(
            selected.getString(
                "status"
            ) ==
                    "operational_configuration_calibrated"
        )

        verifyOperationalValues(
            operational,
            "operational_config.json"
        )

        verifyOperationalValues(
            selected,
            "operational_config_lock.json:selected_values"
        )
    }

    private fun verifyOperationalValues(
        source: JSONObject,
        sourceName: String
    ) {
        check(
            source.getString(
                "revision"
            ) == revision
        ) {
            "revision tidak sesuai $sourceName"
        }

        check(
            source.getInt(
                "analysis_fps"
            ) == fps
        ) {
            "analysis_fps tidak sesuai $sourceName"
        }

        check(
            source.getInt(
                "threads"
            ) == threads
        ) {
            "threads tidak sesuai $sourceName"
        }

        checkClose(
            json.getDouble(
                "roi_width_fraction"
            ),
            source.getDouble(
                "roi_width_fraction"
            ),
            "roi_width_fraction $sourceName"
        )

        checkClose(
            json.getDouble(
                "roi_aspect_ratio"
            ),
            source.getDouble(
                "roi_aspect_ratio"
            ),
            "roi_aspect_ratio $sourceName"
        )

        checkClose(
            json.getDouble(
                "roi_height_cap_fraction"
            ),
            source.getDouble(
                "roi_height_cap_fraction"
            ),
            "roi_height_cap_fraction $sourceName"
        )

        checkClose(
            blurMin,
            source.getDouble(
                "blur_variance_min"
            ),
            "blur_variance_min $sourceName"
        )

        checkClose(
            lumaMin,
            source.getDouble(
                "luma_min"
            ),
            "luma_min $sourceName"
        )

        checkClose(
            lumaMax,
            source.getDouble(
                "luma_max"
            ),
            "luma_max $sourceName"
        )

        checkClose(
            json.getDouble(
                "confidence_threshold"
            ),
            source.getDouble(
                "confidence_threshold"
            ),
            "confidence_threshold $sourceName"
        )

        check(
            source.getLong(
                "temporal_window_ms"
            ) == windowMs
        ) {
            "temporal_window_ms tidak sesuai $sourceName"
        }

        check(
            source.getInt(
                "minimum_results"
            ) == minimumResults
        ) {
            "minimum_results tidak sesuai $sourceName"
        }

        check(
            source.getBoolean(
                "clahe_enabled"
            ) == clahe
        ) {
            "clahe_enabled tidak sesuai $sourceName"
        }

        checkOptionalDouble(
            clipLimit,
            nullableDouble(
                source,
                "clahe_clip_limit"
            ),
            "clahe_clip_limit $sourceName"
        )

        checkOptionalInt(
            grid,
            nullableInt(
                source,
                "clahe_grid"
            ),
            "clahe_grid $sourceName"
        )

        check(
            source.getString(
                "yuv_range"
            ) == yuvRange
        ) {
            "yuv_range tidak sesuai $sourceName"
        }

        check(
            source.getBoolean(
                "log_enabled"
            ) == logging
        ) {
            "log_enabled tidak sesuai $sourceName"
        }
    }

    private fun checkOptionalDouble(
        actual: Double?,
        expected: Double?,
        name: String
    ) {
        if (
            actual == null ||
            expected == null
        ) {
            check(
                actual == expected
            ) {
                "$name tidak sesuai bukti kalibrasi"
            }

            return
        }

        checkClose(
            actual,
            expected,
            name
        )
    }

    private fun checkOptionalInt(
        actual: Int?,
        expected: Int?,
        name: String
    ) {
        check(
            actual == expected
        ) {
            "$name tidak sesuai bukti kalibrasi"
        }
    }

    private fun checkClose(
        actual: Double,
        expected: Double,
        name: String
    ) {
        check(
            abs(
                actual - expected
            ) <= 1e-9
        ) {
            "$name tidak sesuai bukti kalibrasi"
        }
    }

    companion object {

        private const val OPERATIONAL_CONFIG_ASSET =
            "calibration/operational_config.json"

        private const val OPERATIONAL_LOCK_ASSET =
            "calibration/operational_config_lock.json"

        private const val OPERATIONAL_LOCK_SHA256 =
            "f45b1bb88fab2a520b3e46a0f769881056938a212f452324cea4d8eb9939420a"

        fun load(
            context: Context
        ): AppConfig {
            val raw =
                context.assets
                    .open(
                        "app_config.json"
                    )
                    .use {
                        String(
                            it.readBytes(),
                            Charsets.UTF_8
                        )
                    }

            val config =
                AppConfig(raw)

            config.verifyStaticQualityEvidence(
                context
            )

            config.verifyOperationalEvidence(
                context
            )

            return config
        }

        private fun nullableDouble(
            source: JSONObject,
            name: String
        ): Double? =
            if (
                !source.has(name) ||
                source.isNull(name)
            ) {
                null
            } else {
                source.getDouble(name)
            }

        private fun nullableInt(
            source: JSONObject,
            name: String
        ): Int? =
            if (
                !source.has(name) ||
                source.isNull(name)
            ) {
                null
            } else {
                source.getInt(name)
            }

        private fun sha256(
            bytes: ByteArray
        ) =
            MessageDigest
                .getInstance(
                    "SHA-256"
                )
                .digest(bytes)
                .joinToString("") {
                    "%02x".format(
                        it.toInt() and 255
                    )
                }
    }
}