package id.ac.ub.rupiah.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import id.ac.ub.rupiah.config.AppConfig
import id.ac.ub.rupiah.image.RoiGeometry

class RoiOverlay @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {
    var config: AppConfig? = null
        set(value) { field = value; invalidate() }
    private val dark = Paint().apply { color = 0x66000000 }
    private val border = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; style = Paint.Style.STROKE; strokeWidth = 3 * resources.displayMetrics.density }
    private val editConfig by lazy {
        try {
            AppConfig(
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
            )
        } catch (_: Exception) {
            null
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cfg = config ?: if (isInEditMode) editConfig else return
        if (cfg == null) return
        val rect = RoiGeometry.rect(width, height, cfg)
        canvas.drawRect(0f, 0f, width.toFloat(), rect.top, dark)
        canvas.drawRect(0f, rect.bottom, width.toFloat(), height.toFloat(), dark)
        canvas.drawRect(0f, rect.top, rect.left, rect.bottom, dark)
        canvas.drawRect(rect.right, rect.top, width.toFloat(), rect.bottom, dark)
        canvas.drawRoundRect(rect, 8f, 8f, border)
    }
}
