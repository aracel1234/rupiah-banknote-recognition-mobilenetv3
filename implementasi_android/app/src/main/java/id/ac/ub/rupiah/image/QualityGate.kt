package id.ac.ub.rupiah.image

import id.ac.ub.rupiah.config.AppConfig

/**
 * CLAHE kondisional pada ROI redup sebelum pemeriksaan blur.
 * Buffer luminans diubah langsung jika CLAHE diterapkan.
 */
class QualityGate(private val config: AppConfig) {

    private val clahe = LuminanceClahe(config.grid, config.clipLimit)

    data class Result(
        val mean: Double,
        val variance: Double,
        val reason: String?,
        val enhance: Boolean,
        val processedMean: Double = mean
    )

    fun inspect(
        y: FloatArray,
        width: Int,
        height: Int
    ): Result {
        require(width >= 3 && height >= 3 && y.size == width * height)

        val originalMean = mean(y)
        val enhanced = config.clahe && originalMean < config.lumaMin

        if (enhanced) {
            // CLAHE menggunakan rentang 0..255.
            if (config.limitedYuv) {
                for (i in y.indices) {
                    y[i] = ((y[i] - 16f) * (255f / 219f))
                        .coerceIn(0f, 255f)
                }
            }

            clahe.apply(y, width, height)

            // Kembalikan ke rentang Y native untuk konversi YUV berikutnya.
            if (config.limitedYuv) {
                for (i in y.indices) {
                    y[i] = 16f + y[i] * (219f / 255f)
                }
            }
        }

        val processedMean = if (enhanced) mean(y) else originalMean
        val variance = laplacianVariance(y, width, height)

        val reason = when {
            processedMean > config.lumaMax ->
                "Pencahayaan terlalu terang"

            processedMean < config.lumaMin ->
                "Pencahayaan terlalu redup"

            variance < config.blurMin ->
                "Citra buram, stabilkan uang atau kamera"

            else -> null
        }

        return Result(
            mean = originalMean,
            variance = variance,
            reason = reason,
            enhance = enhanced,
            processedMean = processedMean
        )
    }

    private fun mean(y: FloatArray): Double {
        var sum = 0.0

        for (value in y) {
            sum += value
        }

        return sum / y.size
    }

    private fun laplacianVariance(
        y: FloatArray,
        width: Int,
        height: Int
    ): Double {
        var sum = 0.0
        var squared = 0.0

        for (row in 1 until height - 1) {
            for (col in 1 until width - 1) {
                val i = row * width + col

                val lap = (
                        y[i - 1] +
                                y[i + 1] +
                                y[i - width] +
                                y[i + width] -
                                4 * y[i]
                        ).toDouble()

                sum += lap
                squared += lap * lap
            }
        }

        val n = (width - 2) * (height - 2)
        val average = sum / n

        return (squared / n - average * average)
            .coerceAtLeast(0.0)
    }
}