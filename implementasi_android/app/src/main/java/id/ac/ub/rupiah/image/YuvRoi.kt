package id.ac.ub.rupiah.image

import androidx.camera.core.ImageProxy
import id.ac.ub.rupiah.config.AppConfig
import kotlin.math.roundToInt

/** ROI sampling uses actual plane offsets, rowStride and pixelStride, including UV sharing. */
class YuvRoi(
    private val image: ImageProxy,
    config: AppConfig
) {

    private val crop =
        image.cropRect

    private val rotation =
        image.imageInfo.rotationDegrees

    private val rotated =
        rotation == 90 ||
                rotation == 270

    private val orientedWidth =
        if (rotated) {
            crop.height()
        } else {
            crop.width()
        }

    private val orientedHeight =
        if (rotated) {
            crop.width()
        } else {
            crop.height()
        }

    private val roi =
        RoiGeometry.rect(
            orientedWidth,
            orientedHeight,
            config
        )

    private val left =
        roi.left
            .roundToInt()
            .coerceIn(
                0,
                orientedWidth - 1
            )

    private val top =
        roi.top
            .roundToInt()
            .coerceIn(
                0,
                orientedHeight - 1
            )

    val width =
        (
                roi.right
                    .roundToInt()
                    .coerceAtMost(
                        orientedWidth
                    ) -
                        left
                ).coerceAtLeast(1)

    val height =
        (
                roi.bottom
                    .roundToInt()
                    .coerceAtMost(
                        orientedHeight
                    ) -
                        top
                ).coerceAtLeast(1)

    private val planes =
        image.planes

    private val offsets =
        IntArray(3) {
            planes[it]
                .buffer
                .position()
        }

    init {
        require(
            rotation in setOf(
                0,
                90,
                180,
                270
            ) &&
                    width >= 3 &&
                    height >= 3
        )
    }

    private fun pixel(
        x: Int,
        y: Int
    ): Int {
        val ox =
            left + x

        val oy =
            top + y

        val sx: Int
        val sy: Int

        when (rotation) {
            90 -> {
                sx = oy
                sy =
                    crop.height() -
                            1 -
                            ox
            }

            180 -> {
                sx =
                    crop.width() -
                            1 -
                            ox

                sy =
                    crop.height() -
                            1 -
                            oy
            }

            270 -> {
                sx =
                    crop.width() -
                            1 -
                            oy

                sy = ox
            }

            else -> {
                sx = ox
                sy = oy
            }
        }

        return (
                sy + crop.top
                ) *
                image.width +
                sx +
                crop.left
    }

    fun channel(
        channel: Int,
        x: Int,
        y: Int
    ): Int {
        val location =
            pixel(
                x,
                y
            )

        val divisor =
            if (channel == 0) {
                1
            } else {
                2
            }

        val sx =
            location %
                    image.width /
                    divisor

        val sy =
            location /
                    image.width /
                    divisor

        val p =
            planes[channel]

        return p.buffer
            .get(
                offsets[channel] +
                        sy * p.rowStride +
                        sx * p.pixelStride
            )
            .toInt() and 255
    }

    fun copyLuminance(
        destination: FloatArray
    ) {
        for (y in 0 until height) {
            for (x in 0 until width) {
                destination[
                    y * width + x
                ] =
                    channel(
                        0,
                        x,
                        y
                    ).toFloat()
            }
        }
    }
}