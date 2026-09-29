package id.ac.ub.rupiah.sequence

import android.graphics.RectF
import kotlin.math.min

object RoiGeometry {
    fun rect(width: Int, height: Int, config: SequenceConfig): RectF {
        val w = min(width * config.roiFraction, height * 0.90f * config.roiAspect)
        val h = w / config.roiAspect
        return RectF(
            (width - w) / 2f,
            (height - h) / 2f,
            (width + w) / 2f,
            (height + h) / 2f
        )
    }
}
