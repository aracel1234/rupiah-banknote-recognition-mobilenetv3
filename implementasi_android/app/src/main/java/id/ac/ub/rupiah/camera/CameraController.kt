package id.ac.ub.rupiah.camera

import android.content.Context
import android.util.Size
import android.os.Handler
import android.os.Looper
import androidx.camera.core.Camera
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
import java.util.concurrent.Executor

/** Main-thread owner of camera use cases. Shared ViewPort makes center ROI match preview. */
class CameraController(private val context: Context, private val owner: LifecycleOwner,
    private val view: PreviewView, private val worker: Executor) {
    private var provider: ProcessCameraProvider? = null
    private var analysis: ImageAnalysis? = null
    private var preview: Preview? = null
    private var request = 0
    private var boundCamera: Camera? = null
    private val main = Handler(Looper.getMainLooper())
    var front = false; private set
    init { view.scaleType = PreviewView.ScaleType.FILL_CENTER }
    fun bind(wantFront: Boolean, onFrame: (ImageProxy) -> Unit, onReady: (Boolean) -> Unit, onError: (String) -> Unit) {
        val ticket = ++request
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (ticket != request) return@addListener
            try {
                provider = future.get()
                val p = provider!!
                val selector = selector(wantFront)
                if (!p.hasCamera(selector)) { onError("Kamera yang dipilih tidak tersedia"); return@addListener }
                // Only after PreviewView has layout dimensions; no guessed screen pixel coordinates.
                val viewport = view.viewPort ?: run { onError("Area kamera belum siap. Mulai kembali."); return@addListener }
                unbindOwned()
                val rotation = view.display.rotation
                val resolution = ResolutionSelector.Builder().setResolutionStrategy(
                    ResolutionStrategy(Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER)).build()
                val previewCase = Preview.Builder().setTargetRotation(rotation).setResolutionSelector(resolution).build()
                val analysisCase = ImageAnalysis.Builder().setTargetRotation(rotation).setResolutionSelector(resolution)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                preview = previewCase; analysis = analysisCase
                previewCase.setSurfaceProvider(view.surfaceProvider)
                analysisCase.setAnalyzer(worker) { frame -> onFrame(frame) }
                val group = UseCaseGroup.Builder().setViewPort(viewport).addUseCase(previewCase).addUseCase(analysisCase).build()
                val bound = p.bindToLifecycle(owner, selector, group)
                boundCamera = bound
                bound.cameraInfo.cameraState.observe(owner) { state ->
                    if (state.error != null) main.post {
                        if (ticket == request) onError("Kamera mengalami gangguan. Tutup aplikasi kamera lain lalu mulai kembali.")
                    }
                }
                front = wantFront
                var notified = false
                main.postDelayed({
                    if (ticket == request && !notified) onError("Pratinjau kamera belum tersedia. Mulai kembali.")
                }, 10000L)
                view.previewStreamState.removeObservers(owner)
                view.previewStreamState.observe(owner) { state ->
                    if (ticket == request && !notified && state == PreviewView.StreamState.STREAMING) {
                        notified = true; onReady(front)
                    }
                }
            } catch (e: Exception) { onError("Kamera tidak dapat dibuka: ${e.javaClass.simpleName}") }
        }, ContextCompat.getMainExecutor(context))
    }
    private fun selector(front: Boolean) = if (front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA
    private fun unbindOwned() {
        view.previewStreamState.removeObservers(owner)
        boundCamera?.cameraInfo?.cameraState?.removeObservers(owner)
        boundCamera = null
        analysis?.clearAnalyzer()
        analysis?.let { provider?.unbind(it) }; preview?.let { provider?.unbind(it) }
        analysis = null; preview = null
    }
    fun stop() { request++; unbindOwned() }
}
