package id.ac.ub.rupiah.image

import androidx.camera.core.ImageProxy
import id.ac.ub.rupiah.config.AppConfig
import java.nio.ByteBuffer
import kotlin.math.floor

class FramePreprocessor(private val config: AppConfig) {
    private var luminance = FloatArray(0)
    private var rgb = FloatArray(0)
    private val gate = QualityGate(config)
    private val clahe = LuminanceClahe(config.grid, config.clipLimit)
    fun prepare(image: ImageProxy, input: ByteBuffer): QualityGate.Result {
        val roi = YuvRoi(image, config)
        val count = roi.width * roi.height
        if (luminance.size != count) { luminance = FloatArray(count); rgb = FloatArray(count * 3) }
        roi.copyLuminance(luminance)
        val quality = gate.inspect(luminance, roi.width, roi.height)
        if (quality.reason != null) return quality
        if (quality.enhance) clahe.apply(luminance, roi.width, roi.height)
        for (y in 0 until roi.height) for (x in 0 until roi.width) {
            val i = y * roi.width + x
            val u = roi.channel(1, x, y) - 128f; val v = roi.channel(2, x, y) - 128f
            val lum = if (config.limitedYuv) 1.16438356f * (luminance[i] - 16f) else luminance[i]
            rgb[3 * i] = (lum + (if (config.limitedYuv) 1.5960268f else 1.402f) * v).coerceIn(0f, 255f)
            rgb[3 * i + 1] = (lum - (if (config.limitedYuv) 0.3917623f else 0.344136f) * u - (if (config.limitedYuv) 0.8129676f else 0.714136f) * v).coerceIn(0f, 255f)
            rgb[3 * i + 2] = (lum + (if (config.limitedYuv) 2.017232f else 1.772f) * u).coerceIn(0f, 255f)
        }
        resizeBilinear(rgb, roi.width, roi.height, input)
        return quality
    }
    private fun resizeBilinear(source: FloatArray, width: Int, height: Int, destination: ByteBuffer) {
        destination.clear()
        // Half-pixel centers, clamped edges, no antialias or aspect preservation: tf.image.resize.
        for (y in 0 until 224) {
            val sy = ((y + 0.5f) * height / 224f - 0.5f).coerceIn(0f, height - 1f)
            val y0 = floor(sy).toInt(); val y1 = (y0 + 1).coerceAtMost(height - 1); val fy = sy - y0
            for (x in 0 until 224) {
                val sx = ((x + 0.5f) * width / 224f - 0.5f).coerceIn(0f, width - 1f)
                val x0 = floor(sx).toInt(); val x1 = (x0 + 1).coerceAtMost(width - 1); val fx = sx - x0
                for (c in 0..2) {
                    val a = source[(y0 * width + x0) * 3 + c]
                    val b = source[(y0 * width + x1) * 3 + c]
                    val d = source[(y1 * width + x0) * 3 + c]
                    val e = source[(y1 * width + x1) * 3 + c]
                    val upper = a + (b - a) * fx; val lower = d + (e - d) * fx
                    destination.putFloat(upper + (lower - upper) * fy)
                }
            }
        }
        destination.rewind()
    }
}
