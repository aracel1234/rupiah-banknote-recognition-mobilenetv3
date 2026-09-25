package id.ac.ub.rupiah.image

import android.graphics.RectF
import id.ac.ub.rupiah.config.AppConfig
import kotlin.math.min

object RoiGeometry {

    /** Same centered rectangle in PreviewView and the oriented shared ViewPort crop. */
    fun rect(
        width: Int,
        height: Int,
        config: AppConfig
    ): RectF {
        val w =
            min(
                width * config.roiFraction,
                height *
                        0.90f *
                        config.roiAspect
            )

        val h =
            w / config.roiAspect

        return RectF(
            (width - w) / 2f,
            (height - h) / 2f,
            (width + w) / 2f,
            (height + h) / 2f
        )
    }
}