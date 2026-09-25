package id.ac.ub.rupiah.config

import android.content.Context
import org.json.JSONObject

/** All operational choices are explicit. Development defaults are not calibration results. */
data class AppConfig(val raw: String) {
    private val json = JSONObject(raw)
    val status = json.getString("status")
    val fps = json.getInt("analysis_fps")
    val threads = json.getInt("threads")
    val roiFraction = json.getDouble("roi_width_fraction").toFloat()
    val roiAspect = json.getDouble("roi_aspect_ratio").toFloat()
    val blurMin = json.getDouble("blur_variance_min")
    val lumaMin = json.getDouble("luma_min")
    val lumaMax = json.getDouble("luma_max")
    val threshold = json.getDouble("confidence_threshold").toFloat()
    val windowMs = json.getLong("temporal_window_ms")
    val minimumResults = json.getInt("minimum_results")
    val clahe = json.getBoolean("clahe_enabled")
    val clipLimit = json.getDouble("clahe_clip_limit")
    val grid = json.getInt("clahe_grid")
    val limitedYuv = json.getString("yuv_range") == "limited_bt601"
    val logging = json.getBoolean("log_enabled")
    init {
        require(json.getInt("schema_version") == 1)
        require(status in setOf("development_uncalibrated", "calibrated"))
        require(fps in 1..5 && threads in 1..4)
        require(roiFraction in 0.5f..0.95f && roiAspect in 1f..4f)
        require(blurMin.isFinite() && blurMin >= 0)
        require(lumaMin >= 0 && lumaMax <= 255 && lumaMin < lumaMax)
        require(threshold in 0.5f..0.95f && windowMs in 1000L..2000L && minimumResults >= 3)
        require(clipLimit in 1.5..2.5 && grid in setOf(4, 8))
        require(json.getString("yuv_range") in setOf("limited_bt601", "full_bt601"))
        if (status == "calibrated") require(json.getString("calibration_evidence_sha256").matches(Regex("[a-f0-9]{64}")))
    }
    companion object {
        fun load(context: Context): AppConfig {
            val jsonString = try {
                context.assets.open("app_config.json").bufferedReader().use { it.readText() }
            } catch (_: Exception) {
                """{
                  "schema_version": 1,
                  "status": "development_uncalibrated",
                  "revision": "dev-001",
                  "analysis_fps": 3,
                  "threads": 4,
                  "roi_width_fraction": 0.8,
                  "roi_aspect_ratio": 1.3420920964096548,
                  "blur_variance_min": 35.0,
                  "luma_min": 45.0,
                  "luma_max": 220.0,
                  "confidence_threshold": 0.8,
                  "temporal_window_ms": 1500,
                  "minimum_results": 3,
                  "clahe_enabled": false,
                  "clahe_clip_limit": 2.0,
                  "clahe_grid": 4,
                  "yuv_range": "limited_bt601",
                  "log_enabled": true
                }"""
            }
            return AppConfig(jsonString)
        }
    }
}
