package id.ac.ub.rupiah.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import id.ac.ub.rupiah.config.AppConfig
import id.ac.ub.rupiah.image.RoiGeometry

class RoiOverlay(context: Context, attrs: AttributeSet?) : View(context, attrs) {
    var config: AppConfig? = null
        set(value) { field = value; invalidate() }
    private val dark = Paint().apply { color = 0x66000000 }
    private val border = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; style = Paint.Style.STROKE; strokeWidth = 3 * resources.displayMetrics.density }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val cfg = config ?: return
        val rect = RoiGeometry.rect(width, height, cfg)
        canvas.drawRect(0f, 0f, width.toFloat(), rect.top, dark)
        canvas.drawRect(0f, rect.bottom, width.toFloat(), height.toFloat(), dark)
        canvas.drawRect(0f, rect.top, rect.left, rect.bottom, dark)
        canvas.drawRect(rect.right, rect.top, width.toFloat(), rect.bottom, dark)
        canvas.drawRoundRect(rect, 8f, 8f, border)
    }
}
