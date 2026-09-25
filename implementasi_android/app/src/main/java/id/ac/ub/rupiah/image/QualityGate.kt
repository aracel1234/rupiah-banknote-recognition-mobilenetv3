package id.ac.ub.rupiah.image

import id.ac.ub.rupiah.config.AppConfig

/** Native ROI Y plane; 4-neighbor Laplacian, interior pixels, population variance. */
class QualityGate(
    private val config: AppConfig
) {

    data class Result(
        val mean: Double,
        val variance: Double,
        val reason: String?,
        val enhance: Boolean
    )

    fun inspect(
        y: FloatArray,
        width: Int,
        height: Int
    ): Result {
        val count =
            width * height

        var sum = 0.0

        for (i in 0 until count) {
            sum += y[i]
        }

        val mean =
            sum / count

        var lapSum = 0.0
        var lapSquared = 0.0

        for (row in 1 until height - 1) {
            for (col in 1 until width - 1) {
                val i =
                    row * width + col

                val lap =
                    (
                            y[i - 1] +
                                    y[i + 1] +
                                    y[i - width] +
                                    y[i + width] -
                                    4 * y[i]
                            ).toDouble()

                lapSum += lap
                lapSquared += lap * lap
            }
        }

        val n =
            (width - 2) *
                    (height - 2)

        val variance =
            (
                    lapSquared / n -
                            (lapSum / n) *
                            (lapSum / n)
                    ).coerceAtLeast(0.0)

        val reason =
            when {
                variance < config.blurMin ->
                    "Citra buram, stabilkan uang atau kamera"

                mean > config.lumaMax ->
                    "Pencahayaan terlalu terang"

                mean < config.lumaMin &&
                        !config.clahe ->
                    "Pencahayaan terlalu redup"

                else ->
                    null
            }

        return Result(
            mean,
            variance,
            reason,
            reason == null &&
                    mean < config.lumaMin &&
                    config.clahe
        )
    }
}