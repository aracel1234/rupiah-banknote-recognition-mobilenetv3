package id.ac.ub.rupiah.image

import kotlin.math.floor
import kotlin.math.max

/**
 * Local histogram clipping on Y only. Disabled until application calibration selects it.
 * This implementation has its own deterministic tile/border semantics, not OpenCV parity.
 */
class LuminanceClahe(
    private val grid: Int,
    private val clipLimit: Double
) {

    private val lut =
        Array(grid * grid) {
            FloatArray(256)
        }

    private val histogram =
        IntArray(256)

    fun apply(
        y: FloatArray,
        width: Int,
        height: Int
    ) {
        require(
            width >= grid &&
                    height >= grid
        )

        for (gy in 0 until grid) {
            for (gx in 0 until grid) {
                histogram.fill(0)

                val x0 =
                    gx * width / grid

                val x1 =
                    (gx + 1) * width / grid

                val y0 =
                    gy * height / grid

                val y1 =
                    (gy + 1) * height / grid

                val area =
                    (x1 - x0) *
                            (y1 - y0)

                for (row in y0 until y1) {
                    for (col in x0 until x1) {
                        histogram[
                            y[
                                row * width + col
                            ]
                                .toInt()
                                .coerceIn(
                                    0,
                                    255
                                )
                        ]++
                    }
                }

                val limit =
                    max(
                        1,
                        (
                                clipLimit *
                                        area /
                                        256
                                ).toInt()
                    )

                var excess = 0

                for (i in 0..255) {
                    if (histogram[i] > limit) {
                        excess += histogram[i] - limit
                        histogram[i] = limit
                    }
                }

                val share =
                    excess / 256

                val remainder =
                    excess % 256

                for (i in 0..255) {
                    histogram[i] += share
                }

                if (remainder > 0) {
                    for (i in 0 until remainder) {
                        histogram[
                            i * 256 / remainder
                        ]++
                    }
                }

                var cumulative = 0

                for (i in 0..255) {
                    cumulative += histogram[i]

                    lut[
                        gy * grid + gx
                    ][i] =
                        cumulative *
                                255f /
                                area
                }
            }
        }

        for (row in 0 until height) {
            for (col in 0 until width) {
                val tx =
                    (col + 0.5f) *
                            grid /
                            width -
                            0.5f

                val ty =
                    (row + 0.5f) *
                            grid /
                            height -
                            0.5f

                val ix =
                    floor(tx)
                        .toInt()

                val iy =
                    floor(ty)
                        .toInt()

                val fx =
                    tx - ix

                val fy =
                    ty - iy

                val x0 =
                    ix.coerceIn(
                        0,
                        grid - 1
                    )

                val x1 =
                    (ix + 1).coerceIn(
                        0,
                        grid - 1
                    )

                val y0 =
                    iy.coerceIn(
                        0,
                        grid - 1
                    )

                val y1 =
                    (iy + 1).coerceIn(
                        0,
                        grid - 1
                    )

                val value =
                    y[
                        row * width + col
                    ]
                        .toInt()
                        .coerceIn(
                            0,
                            255
                        )

                val a =
                    lut[
                        y0 * grid + x0
                    ][value] *
                            (1 - fx) +
                            lut[
                                y0 * grid + x1
                            ][value] *
                            fx

                val b =
                    lut[
                        y1 * grid + x0
                    ][value] *
                            (1 - fx) +
                            lut[
                                y1 * grid + x1
                            ][value] *
                            fx

                y[
                    row * width + col
                ] =
                    a *
                            (1 - fy) +
                            b *
                            fy
            }
        }
    }
}