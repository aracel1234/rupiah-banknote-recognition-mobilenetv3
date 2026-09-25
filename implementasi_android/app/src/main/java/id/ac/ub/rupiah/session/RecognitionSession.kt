package id.ac.ub.rupiah.session

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.camera.core.ImageProxy
import androidx.camera.view.PreviewView
import androidx.lifecycle.LifecycleOwner
import id.ac.ub.rupiah.camera.CameraController
import id.ac.ub.rupiah.config.AppConfig
import id.ac.ub.rupiah.image.FramePreprocessor
import id.ac.ub.rupiah.inference.ModelRunner
import id.ac.ub.rupiah.logging.EventLog
import id.ac.ub.rupiah.prediction.TemporalDecision
import id.ac.ub.rupiah.speech.SpeechOutput
import java.util.concurrent.Executors

class RecognitionSession(
    private val context: Context,
    owner: LifecycleOwner,
    preview: PreviewView,
    private val config: AppConfig,
    private val ui: (String, String?, Boolean, Boolean) -> Unit,
    private val fatal: (String) -> Unit
) : AutoCloseable {

    private val main = Handler(Looper.getMainLooper())

    private val worker =
        Executors.newSingleThreadExecutor { task ->
            Thread(
                {
                    android.os.Process.setThreadPriority(
                        android.os.Process.THREAD_PRIORITY_BACKGROUND
                    )
                    task.run()
                },
                "RupiahAnalysis"
            )
        }

    private val camera =
        CameraController(
            context,
            owner,
            preview,
            worker
        )

    private val log =
        EventLog(
            context,
            config.logging
        )

    private val processor =
        FramePreprocessor(config)

    private var model: ModelRunner? = null // worker only
    private var decision: TemporalDecision? = null // worker only
    private var lastFrame = 0L // worker only

    @Volatile
    private var active = true

    @Volatile
    private var epoch = 0

    private var modelReady = false
    private var speechReady = false
    private var binding = false
    private var streaming = false
    private var speech: SpeechOutput? = null

    init {
        log.event(
            "session_start",
            "config" to config.raw,
            "config_sha256" to ModelRunner.sha256(
                config.raw.toByteArray()
            ),
            "device" to android.os.Build.MODEL,
            "sdk" to android.os.Build.VERSION.SDK_INT
        )

        ui(
            "Menyiapkan sistem",
            null,
            false,
            false
        )

        speech =
            SpeechOutput(
                context,
                log,
                { error ->
                    if (active) {
                        if (error != null) {
                            fail(error)
                        } else {
                            speechReady = true
                            beginWhenReady()
                        }
                    }
                },
                {
                    if (active) {
                        fail(
                            "Suara tidak dapat diputar. Periksa setelan Text-to-Speech lalu mulai kembali."
                        )
                    }
                }
            )

        worker.execute {
            try {
                val runner =
                    ModelRunner(
                        context,
                        config.threads
                    )

                model = runner
                decision =
                    TemporalDecision(
                        config,
                        runner.labels
                    )

                log.event(
                    "model_loaded",
                    "sha256" to runner.hash,
                    "threads" to config.threads,
                    "runtime" to "TFLite 2.17.0 CPU_XNNPACK"
                )

                main.post {
                    if (active) {
                        modelReady = true
                        beginWhenReady()
                    }
                }
            } catch (e: Exception) {
                main.post {
                    if (active) {
                        fail(
                            "Model tidak dapat disiapkan. Periksa aset aplikasi."
                        )
                    }
                }

                log.event(
                    "model_error",
                    "error" to e.toString()
                )
            }
        }
    }

    private fun beginWhenReady() {
        if (
            active &&
            modelReady &&
            speechReady &&
            !binding
        ) {
            bind(
                false,
                false
            )
        }
    }

    private fun bind(
        front: Boolean,
        rollback: Boolean
    ) {
        if (!active) return

        binding = true
        streaming = false

        val token = ++epoch

        worker.execute {
            decision?.reset()
            lastFrame = 0L
        }

        speech?.stop()

        ui(
            "Menyiapkan kamera",
            null,
            front,
            false
        )

        val previous = camera.front

        camera.bind(
            front,
            { image ->
                analyze(
                    image,
                    token
                )
            },
            { actual ->
                if (
                    active &&
                    token == epoch
                ) {
                    binding = false
                    streaming = true

                    ui(
                        if (actual) {
                            "Kamera depan aktif"
                        } else {
                            "Kamera belakang aktif"
                        },
                        null,
                        actual,
                        true
                    )

                    speech?.camera(actual)

                    log.event(
                        "camera_ready",
                        "front" to actual,
                        "epoch" to token
                    )
                }
            },
            { message ->
                if (
                    active &&
                    token == epoch
                ) {
                    log.event(
                        "camera_error",
                        "message" to message
                    )

                    if (rollback) {
                        bind(
                            previous,
                            false
                        )

                        // Failure feedback is one event, never repeated per frame.
                        speech?.say(
                            "Kamera tidak dapat diganti"
                        )
                    } else {
                        fail(message)
                    }
                }
            }
        )
    }

    fun switchCamera() {
        if (
            active &&
            streaming &&
            !binding
        ) {
            bind(
                !camera.front,
                true
            )
        }
    }

    private fun analyze(
        image: ImageProxy,
        token: Int
    ) {
        try {
            if (
                !active ||
                token != epoch
            ) {
                return
            }

            val start =
                SystemClock.elapsedRealtime()

            if (
                start - lastFrame <
                (1000L + config.fps - 1) / config.fps
            ) {
                return
            }

            lastFrame = start

            val runner =
                model ?: return

            val state =
                decision ?: return

            val quality =
                processor.prepare(
                    image,
                    runner.input
                )

            val prepared =
                SystemClock.elapsedRealtime()

            val result: TemporalDecision.Result
            var scores: FloatArray? = null

            if (quality.reason != null) {
                result =
                    state.reject(
                        start,
                        quality.reason
                    )
            } else {
                scores = runner.run()

                result =
                    state.accept(
                        scores,
                        start
                    )
            }

            val ended =
                SystemClock.elapsedRealtime()

            if (
                !active ||
                token != epoch
            ) {
                return
            }

            if (
                result.announce &&
                result.label != null
            ) {
                state.markAnnounced(
                    result.label
                )
            }

            log.frame(
                "quality_mean_y" to quality.mean,
                "quality_laplacian_variance" to quality.variance,
                "preprocess_ms" to prepared - start,
                "inference_ms" to ended - prepared,
                "pipeline_ms" to ended - start,
                "status" to result.status,
                "scores" to scores?.joinToString(","),
                "label" to result.label,
                "clahe" to quality.enhance
            )

            main.post {
                if (
                    active &&
                    token == epoch &&
                    streaming
                ) {
                    ui(
                        result.status,
                        result.label,
                        camera.front,
                        true
                    )

                    if (
                        result.announce &&
                        result.label != null
                    ) {
                        if (
                            speech?.nominal(
                                result.label
                            ) != true
                        ) {
                            fail(
                                "Suara tidak dapat diputar. Periksa setelan Text-to-Speech."
                            )
                        } else {
                            log.event(
                                "nominal_announced",
                                "label" to result.label
                            )
                        }
                    }
                } else if (
                    active &&
                    token == epoch &&
                    result.announce
                ) {
                    // Preview was not streaming yet: allow a fresh decision, no lost first announcement.
                    worker.execute {
                        decision?.reset()
                    }
                }
            }
        } catch (e: Exception) {
            log.event(
                "pipeline_error",
                "error" to e.toString()
            )

            main.post {
                if (
                    active &&
                    token == epoch
                ) {
                    fail(
                        "Pengenalan terhenti karena kesalahan pemrosesan. Mulai kembali."
                    )
                }
            }
        } finally {
            image.close()
        }
    }

    private fun fail(message: String) {
        close()
        fatal(message)
    }

    override fun close() {
        if (!active) return

        active = false
        epoch++

        camera.stop()
        speech?.close()
        speech = null

        // Close after pending inference; never close Interpreter concurrently with invoke.
        worker.execute {
            decision?.reset()
            model?.close()
            model = null
            log.event("session_closed")
        }

        worker.shutdown()
    }
}