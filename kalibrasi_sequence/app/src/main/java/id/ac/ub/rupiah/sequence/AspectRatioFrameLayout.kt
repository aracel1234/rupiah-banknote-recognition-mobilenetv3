package id.ac.ub.rupiah.sequence

import android.content.Context
import android.util.AttributeSet
import android.widget.FrameLayout
import kotlin.math.roundToInt

/**
 * Container preview kamera dengan rasio lebar:tinggi 4:3.
 *
 * SequenceCamera menggunakan resolusi acuan 640x480 untuk ImageAnalysis.
 * Container ini hanya mengatur ukuran tampilan preview agar tidak menjadi
 * sangat pendek pada layar kecil seperti Redmi 4X.
 *
 * Kelas ini TIDAK mengubah:
 * - ImageAnalysis
 * - ROI
 * - preprocessing
 * - model TensorFlow Lite
 * - frame yang direkam
 * - data sequence
 */
class AspectRatioFrameLayout @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : FrameLayout(context, attrs, defStyleAttr) {

    private val targetAspectRatio = 4f / 3f

    private val minPreviewHeightPx: Int
        get() = (220f * resources.displayMetrics.density).roundToInt()

    private val maxPreviewHeightPx: Int
        get() = (320f * resources.displayMetrics.density).roundToInt()

    override fun onMeasure(
        widthMeasureSpec: Int,
        heightMeasureSpec: Int
    ) {
        val measuredWidth = MeasureSpec.getSize(widthMeasureSpec)

        val contentWidth = (
                measuredWidth -
                        paddingLeft -
                        paddingRight
                ).coerceAtLeast(1)

        val ratioHeight =
            (contentWidth / targetAspectRatio).roundToInt() +
                    paddingTop +
                    paddingBottom

        val targetHeight = ratioHeight.coerceIn(
            minPreviewHeightPx,
            maxPreviewHeightPx
        )

        val exactHeightSpec = MeasureSpec.makeMeasureSpec(
            targetHeight,
            MeasureSpec.EXACTLY
        )

        super.onMeasure(
            widthMeasureSpec,
            exactHeightSpec
        )
    }
}