package id.ac.ub.rupiah

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import id.ac.ub.rupiah.inference.ModelRunner
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.Locale
import kotlin.math.floor


@RunWith(AndroidJUnit4::class)
class ReferenceInferenceInstrumentedTest {

    companion object {
        private const val INPUT_WIDTH = 224
        private const val INPUT_HEIGHT = 224
        private const val CHANNELS = 3
        private const val NUM_CLASSES = 8
        private const val NUM_THREADS = 4

        private val EXPECTED_LABELS = listOf(
            "1000",
            "2000",
            "5000",
            "10000",
            "20000",
            "50000",
            "100000",
            "nonuang"
        )
    }


    data class ReferenceItem(
        val referenceId: String,
        val sampleId: String,
        val classIndex: Int,
        val label: String,
        val sourceId: String,
        val referenceFile: String,
        val sha256: String
    )


    data class TensorStats(
        val min: Float,
        val max: Float
    )


    @Test
    fun runReferenceInference() {

        val instrumentation =
            InstrumentationRegistry.getInstrumentation()

        /*
         * testContext:
         *   berisi assets milik androidTest,
         *   termasuk 16 citra referensi.
         *
         * targetContext:
         *   context aplikasi utama dan assets/model/.
         */
        val testContext = instrumentation.context
        val targetContext =
            ApplicationProvider.getApplicationContext<android.content.Context>()

        val outputDir = File(
            targetContext.filesDir,
            "reference_validation"
        )

        if (!outputDir.exists()) {
            check(outputDir.mkdirs()) {
                "Tidak dapat membuat direktori output: $outputDir"
            }
        }

        val predictionsFile =
            File(outputDir, "android_predictions.csv")

        val summaryFile =
            File(outputDir, "android_inference_summary.json")

        val references = loadReferenceManifest(
            testContext.assets.open(
                "reference/reference_manifest.json"
            ).bufferedReader().use {
                it.readText()
            }
        )

        check(references.size == 16) {
            "Jumlah referensi bukan 16: ${references.size}"
        }

        check(
            references
                .map { it.referenceId }
                .distinct()
                .size == 16
        ) {
            "reference_id tidak unik."
        }

        /*
         * Gunakan ModelRunner produksi yang sama dengan aplikasi.
         *
         * ModelRunner sendiri akan memverifikasi:
         * - asset_integrity.json
         * - model hash
         * - selection_lock
         * - tensor contract
         * - class order
         * - FLOAT32 input/output
         * - shape [1,224,224,3] -> [1,8]
         */
        ModelRunner(
            context = targetContext,
            threads = NUM_THREADS
        ).use { model ->

            check(model.labels == EXPECTED_LABELS) {
                "Urutan label ModelRunner berbeda."
            }

            val csv = StringBuilder()

            csv.append(
                listOf(
                    "reference_id",
                    "sample_id",
                    "true_class_index",
                    "true_label",
                    "source_id",
                    "reference_file",
                    "image_sha256",
                    "processing_success",
                    "error_message",
                    "model_sha256",
                    "input_shape",
                    "input_dtype",
                    "input_min",
                    "input_max",
                    "output_shape",
                    "output_dtype",
                    "top_index",
                    "top_label",
                    "top_score",
                    "score_sum",
                    "score_0",
                    "score_1",
                    "score_2",
                    "score_3",
                    "score_4",
                    "score_5",
                    "score_6",
                    "score_7",
                    "preprocess_ms",
                    "inference_ms",
                    "device_manufacturer",
                    "device_model",
                    "sdk_int"
                ).joinToString(",")
            )

            csv.append('\n')

            var successCount = 0
            var groundTruthMatchCount = 0

            for (reference in references) {

                var processingSuccess = false
                var errorMessage = ""

                var imageSha = ""

                var inputMin = Float.NaN
                var inputMax = Float.NaN

                var topIndex = -1
                var topLabel = ""
                var topScore = Float.NaN
                var scoreSum = Float.NaN

                var scores =
                    FloatArray(NUM_CLASSES) {
                        Float.NaN
                    }

                var preprocessMs = Double.NaN
                var inferenceMs = Double.NaN

                try {

                    val assetPath =
                        "reference/images/${reference.referenceFile}"

                    /*
                     * Baca byte mentah lebih dulu sehingga SHA-256
                     * yang diverifikasi adalah file yang benar-benar
                     * masuk APK test.
                     */
                    val imageBytes =
                        testContext.assets
                            .open(assetPath)
                            .use { it.readBytes() }

                    imageSha =
                        sha256(imageBytes)

                    check(
                        imageSha.equals(
                            reference.sha256,
                            ignoreCase = true
                        )
                    ) {
                        "SHA-256 berbeda untuk ${reference.referenceId}"
                    }

                    val bitmapOptions =
                        BitmapFactory.Options().apply {
                            inPreferredConfig =
                                Bitmap.Config.ARGB_8888
                        }

                    val bitmap =
                        BitmapFactory.decodeByteArray(
                            imageBytes,
                            0,
                            imageBytes.size,
                            bitmapOptions
                        ) ?: error(
                            "Bitmap gagal didecode: $assetPath"
                        )

                    try {

                        val preprocessStart =
                            System.nanoTime()

                        /*
                         * Menulis RGB float32 langsung ke
                         * ModelRunner.input menggunakan resize
                         * bilinear yang setara dengan
                         * FramePreprocessor.
                         */
                        val stats =
                            writeBitmapToInput(
                                bitmap = bitmap,
                                destination = model.input
                            )

                        val preprocessEnd =
                            System.nanoTime()

                        inputMin = stats.min
                        inputMax = stats.max

                        check(inputMin >= 0f)
                        check(inputMax <= 255f)

                        val inferenceStart =
                            System.nanoTime()

                        /*
                         * .copyOf() penting karena output internal
                         * ModelRunner digunakan kembali.
                         */
                        scores =
                            model.run().copyOf()

                        val inferenceEnd =
                            System.nanoTime()

                        preprocessMs =
                            (
                                    preprocessEnd -
                                            preprocessStart
                                    ) / 1_000_000.0

                        inferenceMs =
                            (
                                    inferenceEnd -
                                            inferenceStart
                                    ) / 1_000_000.0

                    } finally {
                        bitmap.recycle()
                    }

                    check(scores.size == NUM_CLASSES)

                    check(
                        scores.all {
                            it.isFinite()
                        }
                    )

                    topIndex =
                        scores.indices.maxBy {
                            scores[it]
                        }

                    topLabel =
                        model.labels[topIndex]

                    topScore =
                        scores[topIndex]

                    scoreSum =
                        scores.sum()

                    processingSuccess = true
                    successCount++

                    if (
                        topIndex ==
                        reference.classIndex
                    ) {
                        groundTruthMatchCount++
                    }

                } catch (t: Throwable) {

                    errorMessage =
                        "${t.javaClass.simpleName}: ${t.message.orEmpty()}"
                }

                val row = mutableListOf<String>()

                row += reference.referenceId
                row += reference.sampleId
                row += reference.classIndex.toString()
                row += reference.label
                row += reference.sourceId
                row += reference.referenceFile
                row += imageSha

                row += processingSuccess.toString()
                row += errorMessage

                row += model.hash

                row += "1x224x224x3"
                row += "float32"

                row += floatOrEmpty(inputMin)
                row += floatOrEmpty(inputMax)

                row += "1x8"
                row += "float32"

                row += if (topIndex >= 0) {
                    topIndex.toString()
                } else {
                    ""
                }

                row += topLabel
                row += floatOrEmpty(topScore)
                row += floatOrEmpty(scoreSum)

                for (i in 0 until NUM_CLASSES) {
                    row += floatOrEmpty(
                        scores[i]
                    )
                }

                row += doubleOrEmpty(
                    preprocessMs,
                    digits = 3
                )

                row += doubleOrEmpty(
                    inferenceMs,
                    digits = 3
                )

                row += Build.MANUFACTURER.orEmpty()
                row += Build.MODEL.orEmpty()
                row += Build.VERSION.SDK_INT.toString()

                csv.append(
                    row.joinToString(",") {
                        csvCell(it)
                    }
                )

                csv.append('\n')
            }

            predictionsFile.writeText(
                csv.toString(),
                Charsets.UTF_8
            )

            val summary = JSONObject().apply {

                put(
                    "schema_version",
                    1
                )

                put(
                    "purpose",
                    "Android baseline for Python-Android integration equivalence validation"
                )

                put(
                    "reference_count",
                    references.size
                )

                put(
                    "processing_success_count",
                    successCount
                )

                put(
                    "processing_failed_count",
                    references.size -
                            successCount
                )

                put(
                    "ground_truth_top1_match_count",
                    groundTruthMatchCount
                )

                put(
                    "ground_truth_top1_match_rate",
                    if (successCount > 0) {
                        groundTruthMatchCount
                            .toDouble() /
                                successCount
                    } else {
                        JSONObject.NULL
                    }
                )

                put(
                    "model_sha256",
                    model.hash
                )

                put(
                    "threads",
                    NUM_THREADS
                )

                put(
                    "input_shape",
                    JSONArray(
                        listOf(
                            1,
                            INPUT_HEIGHT,
                            INPUT_WIDTH,
                            CHANNELS
                        )
                    )
                )

                put(
                    "input_dtype",
                    "float32"
                )

                put(
                    "input_external_range",
                    JSONArray(
                        listOf(
                            0,
                            255
                        )
                    )
                )

                put(
                    "resize",
                    "bilinear_half_pixel"
                )

                put(
                    "antialias",
                    false
                )

                put(
                    "output_shape",
                    JSONArray(
                        listOf(
                            1,
                            NUM_CLASSES
                        )
                    )
                )

                put(
                    "output_dtype",
                    "float32"
                )

                put(
                    "class_names",
                    JSONArray(model.labels)
                )

                put(
                    "device_manufacturer",
                    Build.MANUFACTURER
                )

                put(
                    "device_model",
                    Build.MODEL
                )

                put(
                    "device_device",
                    Build.DEVICE
                )

                put(
                    "sdk_int",
                    Build.VERSION.SDK_INT
                )

                put(
                    "android_release",
                    Build.VERSION.RELEASE
                )

                put(
                    "note",
                    "Ground-truth Top-1 hanya informasi tambahan. Kriteria utama adalah kesesuaian Top-1 dan skor terhadap baseline Python untuk citra referensi yang sama."
                )
            }

            summaryFile.writeText(
                summary.toString(2) + "\n",
                Charsets.UTF_8
            )

            check(successCount == 16) {
                "Tidak semua citra berhasil diproses. " +
                        "Berhasil=$successCount/16"
            }
        }
    }


    /**
     * Preprocessing khusus citra statis untuk uji ekuivalensi.
     *
     * Input:
     *   Bitmap RGB/ARGB.
     *
     * Output:
     *   [1, 224, 224, 3]
     *   float32 RGB
     *   rentang [0,255]
     *
     * Tidak:
     * - dibagi 255
     * - memakai MobileNet preprocess_input
     * - menerapkan softmax
     *
     * Algoritma resize mengikuti FramePreprocessor:
     * - bilinear
     * - half-pixel centers
     * - clamped edge
     * - no antialias
     */
    private fun writeBitmapToInput(
        bitmap: Bitmap,
        destination: ByteBuffer
    ): TensorStats {

        val width =
            bitmap.width

        val height =
            bitmap.height

        check(width > 0 && height > 0)

        val pixels =
            IntArray(width * height)

        bitmap.getPixels(
            pixels,
            0,
            width,
            0,
            0,
            width,
            height
        )

        destination.clear()

        var minValue =
            Float.POSITIVE_INFINITY

        var maxValue =
            Float.NEGATIVE_INFINITY

        for (
        y in 0 until INPUT_HEIGHT
        ) {

            val sy =
                (
                        (y + 0.5f) *
                                height /
                                INPUT_HEIGHT -
                                0.5f
                        ).coerceIn(
                        0f,
                        height - 1f
                    )

            val y0 =
                floor(sy).toInt()

            val y1 =
                (y0 + 1)
                    .coerceAtMost(
                        height - 1
                    )

            val fy =
                sy - y0

            for (
            x in 0 until INPUT_WIDTH
            ) {

                val sx =
                    (
                            (x + 0.5f) *
                                    width /
                                    INPUT_WIDTH -
                                    0.5f
                            ).coerceIn(
                            0f,
                            width - 1f
                        )

                val x0 =
                    floor(sx).toInt()

                val x1 =
                    (x0 + 1)
                        .coerceAtMost(
                            width - 1
                        )

                val fx =
                    sx - x0

                val p00 =
                    pixels[
                        y0 * width + x0
                    ]

                val p01 =
                    pixels[
                        y0 * width + x1
                    ]

                val p10 =
                    pixels[
                        y1 * width + x0
                    ]

                val p11 =
                    pixels[
                        y1 * width + x1
                    ]

                for (
                channel in 0 until 3
                ) {

                    val shift =
                        when (channel) {
                            0 -> 16
                            1 -> 8
                            else -> 0
                        }

                    val a =
                        (
                                p00 ushr shift
                                ) and 0xFF

                    val b =
                        (
                                p01 ushr shift
                                ) and 0xFF

                    val d =
                        (
                                p10 ushr shift
                                ) and 0xFF

                    val e =
                        (
                                p11 ushr shift
                                ) and 0xFF

                    val af =
                        a.toFloat()

                    val bf =
                        b.toFloat()

                    val df =
                        d.toFloat()

                    val ef =
                        e.toFloat()

                    val upper =
                        af +
                                (bf - af) *
                                fx

                    val lower =
                        df +
                                (ef - df) *
                                fx

                    val value =
                        upper +
                                (lower - upper) *
                                fy

                    destination.putFloat(
                        value
                    )

                    if (
                        value < minValue
                    ) {
                        minValue = value
                    }

                    if (
                        value > maxValue
                    ) {
                        maxValue = value
                    }
                }
            }
        }

        destination.rewind()

        check(
            destination.capacity() ==
                    INPUT_WIDTH *
                    INPUT_HEIGHT *
                    CHANNELS *
                    4
        )

        return TensorStats(
            min = minValue,
            max = maxValue
        )
    }


    private fun loadReferenceManifest(
        jsonText: String
    ): List<ReferenceItem> {

        val array =
            JSONArray(jsonText)

        return List(
            array.length()
        ) { index ->

            val item =
                array.getJSONObject(
                    index
                )

            ReferenceItem(
                referenceId =
                    item.getString(
                        "reference_id"
                    ),
                sampleId =
                    item.getString(
                        "sample_id"
                    ),
                classIndex =
                    item.getInt(
                        "class_index"
                    ),
                label =
                    item.getString(
                        "label"
                    ),
                sourceId =
                    item.getString(
                        "source_id"
                    ),
                referenceFile =
                    item.getString(
                        "reference_file"
                    ),
                sha256 =
                    item.getString(
                        "sha256"
                    )
            )
        }
    }


    private fun sha256(
        bytes: ByteArray
    ): String {

        return MessageDigest
            .getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") {
                "%02x".format(
                    it.toInt() and 0xFF
                )
            }
    }


    private fun floatOrEmpty(
        value: Float,
        digits: Int = 9
    ): String {

        if (!value.isFinite()) {
            return ""
        }

        return String.format(
            Locale.US,
            "%.${digits}f",
            value
        )
    }


    private fun doubleOrEmpty(
        value: Double,
        digits: Int = 9
    ): String {

        if (!value.isFinite()) {
            return ""
        }

        return String.format(
            Locale.US,
            "%.${digits}f",
            value
        )
    }


    private fun csvCell(
        value: String
    ): String {

        val mustQuote =
            value.contains(",") ||
                    value.contains("\"") ||
                    value.contains("\n") ||
                    value.contains("\r")

        if (!mustQuote) {
            return value
        }

        return "\"" +
                value.replace(
                    "\"",
                    "\"\""
                ) +
                "\""
    }
}