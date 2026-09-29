package id.ac.ub.rupiah.sequence

import android.content.Context
import org.json.JSONObject
import java.security.MessageDigest

data class SequenceConfig(
    val roiFraction: Float,
    val roiAspect: Float,
    val blurMin: Double,
    val lumaMin: Double,
    val lumaMax: Double,
    val claheEnabled: Boolean,
    val claheClipLimit: Double,
    val claheGrid: Int,
    val threads: Int = 4,
    val collectionFps: Int = 5,
    val confirmed: Boolean = false
) {
    init {
        require(roiFraction in setOf(0.70f, 0.80f, 0.90f))
        require(roiAspect in 1f..4f)
        require(blurMin.isFinite() && blurMin >= 0.0)
        require(lumaMin in 0.0..254.0)
        require(lumaMax in 1.0..255.0 && lumaMin < lumaMax)
        require(claheClipLimit in 1.5..2.5)
        require(claheGrid in setOf(4, 8))
        require(threads in 1..4)
        require(collectionFps == 5)
    }

    fun toJson(): JSONObject = JSONObject().apply {
        put("schema_version", 1)
        put("purpose", "Sequence calibration collector configuration after static calibration")
        put("status", if (confirmed) "confirmed_for_sequence_collection" else "unconfirmed")
        put("roi_width_fraction", roiFraction.toDouble())
        put("roi_aspect_ratio", roiAspect.toDouble())
        put("blur_variance_min", blurMin)
        put("luma_min", lumaMin)
        put("luma_max", lumaMax)
        put("clahe_enabled", claheEnabled)
        put("clahe_clip_limit", claheClipLimit)
        put("clahe_grid", claheGrid)
        put("threads", threads)
        put("collection_fps", collectionFps)
        put("yuv_range", "limited_bt601")
        put("note", "Collection runs the same ROI/quality preprocessing as the thesis app. Only quality-passed frames are inferred. Raw quality metrics and all eight scores are logged for offline threshold/window analysis.")
    }

    fun canonicalJson(): String = toJson().toString()
    fun sha256(): String = sha256(canonicalJson().toByteArray(Charsets.UTF_8))

    companion object {
        const val DEFAULT_ROI_ASPECT = 1.3420920964096548f

        fun default(): SequenceConfig = SequenceConfig(
            roiFraction = 0.80f,
            roiAspect = DEFAULT_ROI_ASPECT,
            blurMin = 35.0,
            lumaMin = 45.0,
            lumaMax = 220.0,
            claheEnabled = true,
            claheClipLimit = 2.0,
            claheGrid = 4,
            confirmed = false
        )

        fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}

class SequenceConfigStore(context: Context) {
    private val prefs = context.getSharedPreferences("sequence_config", Context.MODE_PRIVATE)

    fun load(): SequenceConfig {
        return SequenceConfig(
            roiFraction = prefs.getFloat("roi_fraction", 0.80f),
            roiAspect = SequenceConfig.DEFAULT_ROI_ASPECT,
            blurMin = prefs.getString("blur_min", "35.0")!!.toDouble(),
            lumaMin = prefs.getString("luma_min", "45.0")!!.toDouble(),
            lumaMax = prefs.getString("luma_max", "220.0")!!.toDouble(),
            claheEnabled = prefs.getBoolean("clahe_enabled", true),
            claheClipLimit = prefs.getString("clahe_clip", "2.0")!!.toDouble(),
            claheGrid = prefs.getInt("clahe_grid", 4),
            confirmed = prefs.getBoolean("confirmed", false)
        )
    }

    fun save(config: SequenceConfig) {
        prefs.edit()
            .putFloat("roi_fraction", config.roiFraction)
            .putString("blur_min", config.blurMin.toString())
            .putString("luma_min", config.lumaMin.toString())
            .putString("luma_max", config.lumaMax.toString())
            .putBoolean("clahe_enabled", config.claheEnabled)
            .putString("clahe_clip", config.claheClipLimit.toString())
            .putInt("clahe_grid", config.claheGrid)
            .putBoolean("confirmed", config.confirmed)
            .apply()
    }
}
