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
    private val speech: SpeechOutput,
    private val log: EventLog,
    private val ui: (String, String?, Boolean, Boolean) -> Unit,
    private val fatal: (String) -> Unit
) : AutoCloseable {

    private val main = Handler(Looper.getMainLooper())

    private val worker = Executors.newSingleThreadExecutor { task ->
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

    private val camera = CameraController(
        context,
        owner,
        preview,
        worker
    )

    private val processor = FramePreprocessor(config)

    // Diakses pada worker.
    private var model: ModelRunner? = null
    private var decision: TemporalDecision? = null
    private var lastFrame = 0L

    @Volatile
    private var active = true

    @Volatile
    private var epoch = 0

    private var modelReady = false
    private var binding = false
    private var streaming = false
    private var firstCamera = true
    private var announcementPending: String? = null // Worker only.

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

        ui("Menyiapkan sistem", null, false, false)

        worker.execute {
            try {
                val runner = ModelRunner(context, config.threads)

                model = runner
                decision = TemporalDecision(config, runner.labels)

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
                            "Model tidak dapat disiapkan. " +
                                    "Periksa aset aplikasi."
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
        if (active && modelReady && !binding) {
            bind(false, false)
        }
    }

    private fun bind(front: Boolean, rollback: Boolean) {
        if (!active) return

        binding = true
        streaming = false

        val token = ++epoch

        worker.execute {
            decision?.reset()
            announcementPending = null
            lastFrame = 0L
        }

        speech.stop()

        ui("Menyiapkan kamera", null, front, false)

        val previous = camera.front

        camera.bind(
            front,
            { image ->
                analyze(image, token)
            },
            { actual ->
                if (active && token == epoch) {
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

                    speech.camera(actual, starting = firstCamera)
                    firstCamera = false

                    log.event(
                        "camera_ready",
                        "front" to actual,
                        "epoch" to token
                    )
                }
            },
            { message ->
                if (active && token == epoch) {
                    log.event(
                        "camera_error",
                        "message" to message
                    )

                    if (rollback) {
                        bind(previous, false)
                        speech.say("Kamera tidak dapat diganti")
                    } else {
                        fail(message)
                    }
                }
            }
        )
    }

    fun switchCamera() {
        if (active && streaming && !binding) {
            bind(!camera.front, true)
        }
    }

    private fun analyze(image: ImageProxy, token: Int) {
        try {
            if (!active || token != epoch) return

            val start = SystemClock.elapsedRealtime()

            if (start - lastFrame < (1000L + config.fps - 1) / config.fps) {
                return
            }

            lastFrame = start

            val runner = model ?: return
            val state = decision ?: return

            // CLAHE dan pemeriksaan kualitas dilakukan dalam prepare().
            val quality = processor.prepare(image, runner.input)
            val prepared = SystemClock.elapsedRealtime()

            val result: TemporalDecision.Result
            var scores: FloatArray? = null

            if (quality.reason != null) {
                result = state.reject(start, quality.reason)
            } else {
                scores = runner.run()
                result = state.accept(scores, start)
            }

            val ended = SystemClock.elapsedRealtime()

            if (!active || token != epoch) return

            val announce = result.announce && result.label != null && announcementPending == null
            if (announce) announcementPending = result.label

            log.frame(
                "quality_mean_y" to quality.mean,
                "quality_processed_mean_y" to quality.processedMean,
                "quality_laplacian_variance" to quality.variance,
                "quality_policy" to "clahe_before_blur_v2",
                "preprocess_ms" to (prepared - start),
                "inference_ms" to (ended - prepared),
                "pipeline_ms" to (ended - start),
                "status" to result.status,
                "scores" to scores?.joinToString(","),
                "label" to result.label,
                "clahe" to quality.enhance
            )

            main.post {
                if (active && token == epoch && streaming) {
                    ui(
                        result.status,
                        result.label,
                        camera.front,
                        true
                    )

                    if (announce && result.label != null) {
                        if (speech.nominal(result.label) != true) {
                            fail(
                                "Suara tidak dapat diputar. " +
                                        "Periksa setelan Text-to-Speech."
                            )
                        } else {
                            // Acknowledge on the same worker that owns TemporalDecision.
                            worker.execute {
                                if (active && token == epoch) {
                                    decision?.markAnnounced(result.label)
                                    announcementPending = null
                                }
                            }
                            log.event(
                                "nominal_announced",
                                "label" to result.label,
                                "route" to speech.route,
                                "delivery" to "requested_not_confirmed"
                            )
                        }
                    }
                } else if (active && token == epoch && announce) {
                    // Izinkan keputusan baru jika preview belum siap.
                    worker.execute {
                        decision?.reset()
                        announcementPending = null
                    }
                }
            }
        } catch (e: Exception) {
            log.event(
                "pipeline_error",
                "error" to e.toString()
            )

            main.post {
                if (active && token == epoch) {
                    fail(
                        "Pengenalan terhenti karena kesalahan pemrosesan. " +
                                "Mulai kembali."
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
        // Activity owns the output, so a stop confirmation can still be spoken.
        speech.stop()

        // Model ditutup setelah pekerjaan inferensi yang sedang berjalan.
        worker.execute {
            decision?.reset()
            announcementPending = null
            model?.close()
            model = null

            log.event("session_closed")
        }

        worker.shutdown()
    }
}