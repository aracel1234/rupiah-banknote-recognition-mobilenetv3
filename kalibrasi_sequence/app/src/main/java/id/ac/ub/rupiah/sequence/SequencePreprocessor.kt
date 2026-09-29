package id.ac.ub.rupiah.sequence

import androidx.camera.core.ImageProxy
import java.nio.ByteBuffer
import kotlin.math.floor

class SequencePreprocessor(private val config: SequenceConfig) {
    data class Result(
        val originalMean: Double,
        val processedMean: Double,
        val laplacianVariance: Double,
        val qualityCode: String?,
        val claheApplied: Boolean,
        val roiWidth: Int,
        val roiHeight: Int,
        val rotationDegrees: Int
    ) {
        val qualityPass: Boolean get() = qualityCode == null
    }

    private var luminance = FloatArray(0)
    private var rgb = FloatArray(0)
    private val clahe = LuminanceClahe(config.claheGrid, config.claheClipLimit)

    fun prepare(image: ImageProxy, input: ByteBuffer): Result {
        val roi = YuvRoi(image, config)
        val count = roi.width * roi.height
        if (luminance.size != count) {
            luminance = FloatArray(count)
            rgb = FloatArray(count * 3)
        }
        roi.copyLuminance(luminance)

        val originalMean = mean(luminance)
        val enhanced = config.claheEnabled && originalMean < config.lumaMin
        if (enhanced) {
            for (i in luminance.indices) {
                luminance[i] = ((luminance[i] - 16f) * (255f / 219f)).coerceIn(0f, 255f)
            }
            clahe.apply(luminance, roi.width, roi.height)
            for (i in luminance.indices) {
                luminance[i] = 16f + luminance[i] * (219f / 255f)
            }
        }
        val processedMean = if (enhanced) mean(luminance) else originalMean
        val variance = laplacianVariance(luminance, roi.width, roi.height)
        val qualityCode = when {
            processedMean > config.lumaMax -> "too_bright"
            processedMean < config.lumaMin -> "too_dark"
            variance < config.blurMin -> "blur"
            else -> null
        }

        if (qualityCode == null) {
            for (y in 0 until roi.height) {
                for (x in 0 until roi.width) {
                    val i = y * roi.width + x
                    val u = roi.channel(1, x, y) - 128f
                    val v = roi.channel(2, x, y) - 128f
                    val lum = 1.16438356f * (luminance[i] - 16f)
                    rgb[3 * i] = (lum + 1.5960268f * v).coerceIn(0f, 255f)
                    rgb[3 * i + 1] = (lum - 0.3917623f * u - 0.8129676f * v).coerceIn(0f, 255f)
                    rgb[3 * i + 2] = (lum + 2.017232f * u).coerceIn(0f, 255f)
                }
            }
            resizeBilinear(rgb, roi.width, roi.height, input)
        }

        return Result(
            originalMean = originalMean,
            processedMean = processedMean,
            laplacianVariance = variance,
            qualityCode = qualityCode,
            claheApplied = enhanced,
            roiWidth = roi.width,
            roiHeight = roi.height,
            rotationDegrees = roi.rotationDegrees
        )
    }

    private fun mean(y: FloatArray): Double {
        var sum = 0.0
        for (value in y) sum += value
        return sum / y.size
    }

    private fun laplacianVariance(y: FloatArray, width: Int, height: Int): Double {
        var sum = 0.0
        var squared = 0.0
        for (row in 1 until height - 1) {
            for (col in 1 until width - 1) {
                val i = row * width + col
                val lap = (y[i - 1] + y[i + 1] + y[i - width] + y[i + width] - 4 * y[i]).toDouble()
                sum += lap
                squared += lap * lap
            }
        }
        val n = (width - 2) * (height - 2)
        val average = sum / n
        return (squared / n - average * average).coerceAtLeast(0.0)
    }

    private fun resizeBilinear(source: FloatArray, width: Int, height: Int, destination: ByteBuffer) {
        destination.clear()
        for (y in 0 until 224) {
            val sy = ((y + 0.5f) * height / 224f - 0.5f).coerceIn(0f, height - 1f)
            val y0 = floor(sy).toInt()
            val y1 = (y0 + 1).coerceAtMost(height - 1)
            val fy = sy - y0
            for (x in 0 until 224) {
                val sx = ((x + 0.5f) * width / 224f - 0.5f).coerceIn(0f, width - 1f)
                val x0 = floor(sx).toInt()
                val x1 = (x0 + 1).coerceAtMost(width - 1)
                val fx = sx - x0
                for (c in 0..2) {
                    val a = source[(y0 * width + x0) * 3 + c]
                    val b = source[(y0 * width + x1) * 3 + c]
                    val d = source[(y1 * width + x0) * 3 + c]
                    val e = source[(y1 * width + x1) * 3 + c]
                    val upper = a + (b - a) * fx
                    val lower = d + (e - d) * fx
                    destination.putFloat(upper + (lower - upper) * fy)
                }
            }
        }
        destination.rewind()
    }
}
