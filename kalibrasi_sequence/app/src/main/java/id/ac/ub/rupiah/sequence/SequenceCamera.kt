package id.ac.ub.rupiah.sequence

import android.content.Context
import android.os.SystemClock
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.UseCaseGroup
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.ceil

class SequenceCamera(
    private val context: Context,
    private val owner: LifecycleOwner,
    private val previewView: PreviewView,
    private val onReady: (String) -> Unit,
    private val onFrameRecorded: (FrameRecord) -> Unit,
    private val onSequenceFinished: (List<FrameRecord>, SequenceRunStats) -> Unit,
    private val onError: (Throwable) -> Unit
) : AutoCloseable {

    private data class ActiveRun(
        val item: SequenceItem,
        val config: SequenceConfig,
        val startNs: Long,
        val records: MutableList<FrameRecord> = mutableListOf(),
        var lastSampleNs: Long = 0L,
        var cameraFramesSeen: Int = 0,
        var finished: Boolean = false
    )

    private val executor: ExecutorService = Executors.newSingleThreadExecutor { task ->
        Thread(task, "SequenceAnalysis")
    }
    private var provider: ProcessCameraProvider? = null
    private var model: ModelRunner? = null
    private var processor: SequencePreprocessor? = null
    @Volatile private var activeRun: ActiveRun? = null
    @Volatile private var currentConfig: SequenceConfig? = null

    fun start(config: SequenceConfig) {
        currentConfig = config
        previewView.scaleType = PreviewView.ScaleType.FILL_CENTER
        executor.execute {
            try {
                model?.close()
                model = ModelRunner(context, config.threads)
                processor = SequencePreprocessor(config)
                bindCamera()
            } catch (t: Throwable) {
                onError(t)
            }
        }
    }

    fun reconfigure(config: SequenceConfig) {
        check(activeRun == null) { "Tidak dapat mengubah konfigurasi saat sequence berjalan" }
        start(config)
    }

    fun beginSequence(item: SequenceItem) {
        val config = currentConfig ?: error("Konfigurasi belum tersedia")
        check(config.confirmed) { "Konfigurasi 5.7.2 belum dikonfirmasi" }
        check(activeRun == null) { "Sequence lain masih berjalan" }
        activeRun = ActiveRun(item = item, config = config, startNs = SystemClock.elapsedRealtimeNanos())
    }

    fun abortSequence() {
        activeRun = null
    }

    fun isRecording(): Boolean = activeRun != null

    private fun bindCamera() {
        previewView.post {
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener({
                try {
                    val cameraProvider = future.get()
                    provider = cameraProvider
                    cameraProvider.unbindAll()

                    val preview = Preview.Builder().build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }
                    val selector = ResolutionSelector.Builder()
                        .setResolutionStrategy(
                            ResolutionStrategy(
                                Size(640, 480),
                                ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER
                            )
                        ).build()
                    val analysis = ImageAnalysis.Builder()
                        .setResolutionSelector(selector)
                        .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .build()
                    analysis.setAnalyzer(executor) { image -> analyze(image) }

                    val viewPort = previewView.viewPort
                    if (viewPort != null) {
                        val group = UseCaseGroup.Builder()
                            .addUseCase(preview)
                            .addUseCase(analysis)
                            .setViewPort(viewPort)
                            .build()
                        cameraProvider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, group)
                    } else {
                        cameraProvider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                    }
                    val hash = model?.hash ?: "unknown"
                    onReady(hash)
                } catch (t: Throwable) {
                    onError(t)
                }
            }, ContextCompat.getMainExecutor(context))
        }
    }

    private fun analyze(image: ImageProxy) {
        try {
            val run = activeRun ?: return
            if (run.finished) return
            run.cameraFramesSeen++

            val nowNs = SystemClock.elapsedRealtimeNanos()
            val elapsedMs = (nowNs - run.startNs) / 1_000_000L
            if (elapsedMs >= run.item.totalDurationMs) {
                finish(run)
                return
            }

            val minIntervalNs = ceil(1_000_000_000.0 / run.config.collectionFps).toLong()
            if (run.lastSampleNs != 0L && nowNs - run.lastSampleNs < minIntervalNs) return
            run.lastSampleNs = nowNs

            val stage = run.item.stageAt(elapsedMs)
            val runner = model ?: return
            val prep = processor ?: return

            val start = SystemClock.elapsedRealtimeNanos()
            val quality = prep.prepare(image, runner.input)
            val afterPrep = SystemClock.elapsedRealtimeNanos()

            var scores: FloatArray? = null
            var topLabel: String? = null
            var topScore: Float? = null
            if (quality.qualityPass) {
                val result = runner.run().copyOf()
                scores = result
                val winner = result.indices.maxByOrNull { result[it] }!!
                topLabel = runner.labels[winner]
                topScore = result[winner]
            }
            val end = SystemClock.elapsedRealtimeNanos()

            val record = FrameRecord(
                frameIndex = run.records.size + 1,
                elapsedMs = elapsedMs,
                stageId = stage.id,
                stageTitle = stage.title,
                expectedLabel = stage.expectedLabel,
                analysisRole = stage.analysisRole,
                imageTimestampNs = image.imageInfo.timestamp,
                rotationDegrees = quality.rotationDegrees,
                roiWidth = quality.roiWidth,
                roiHeight = quality.roiHeight,
                originalMeanY = quality.originalMean,
                processedMeanY = quality.processedMean,
                laplacianVariance = quality.laplacianVariance,
                claheApplied = quality.claheApplied,
                qualityPass = quality.qualityPass,
                qualityCode = quality.qualityCode,
                scores = scores,
                topLabel = topLabel,
                topScore = topScore,
                preprocessMs = (afterPrep - start) / 1_000_000.0,
                inferenceMs = (end - afterPrep) / 1_000_000.0,
                pipelineMs = (end - start) / 1_000_000.0
            )
            run.records += record
            onFrameRecorded(record)

            if (((SystemClock.elapsedRealtimeNanos() - run.startNs) / 1_000_000L) >= run.item.totalDurationMs) {
                finish(run)
            }
        } catch (t: Throwable) {
            activeRun = null
            onError(t)
        } finally {
            image.close()
        }
    }

    private fun finish(run: ActiveRun) {
        if (run.finished) return
        run.finished = true
        if (activeRun !== run) return
        activeRun = null

        val values = run.records.map { it.pipelineMs }.sorted()
        val median = percentile(values, 0.50)
        val p95 = percentile(values, 0.95)
        val duration = run.item.totalDurationMs
        val qualityPassed = run.records.count { it.qualityPass }
        val achieved = if (duration > 0) run.records.size * 1000.0 / duration else 0.0
        val stats = SequenceRunStats(
            cameraFramesSeen = run.cameraFramesSeen,
            sampledFrames = run.records.size,
            qualityPassedFrames = qualityPassed,
            qualityRejectedFrames = run.records.size - qualityPassed,
            durationMs = duration,
            targetFps = run.config.collectionFps,
            medianPipelineMs = median,
            p95PipelineMs = p95,
            achievedSampleFps = achieved
        )
        onSequenceFinished(run.records.toList(), stats)
    }

    private fun percentile(sorted: List<Double>, p: Double): Double {
        if (sorted.isEmpty()) return 0.0
        val index = ((sorted.size - 1) * p).toInt().coerceIn(0, sorted.lastIndex)
        return sorted[index]
    }

    override fun close() {
        activeRun = null
        provider?.unbindAll()
        executor.execute {
            try { model?.close() } catch (_: Throwable) {}
            model = null
        }
        executor.shutdown()
    }
}
