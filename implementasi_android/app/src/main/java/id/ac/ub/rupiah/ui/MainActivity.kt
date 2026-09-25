package id.ac.ub.rupiah.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import id.ac.ub.rupiah.R
import id.ac.ub.rupiah.config.AppConfig
import id.ac.ub.rupiah.session.RecognitionSession
import java.text.NumberFormat
import java.util.Locale

class MainActivity : ComponentActivity() {
    private lateinit var status: TextView
    private lateinit var nominal: TextView
    private lateinit var toggle: Button
    private lateinit var switchCamera: Button
    private lateinit var preview: PreviewView
    private var config: AppConfig? = null
    private var session: RecognitionSession? = null
    private var foreground = false
    private var wantRecognition = true
    private var permissionPending = false
    private var requestedBefore = false
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        permissionPending = false
        if (granted) {
            wantRecognition = true
            maybeStart()
        }
        else { wantRecognition = false;
            stopped("Izin kamera diperlukan. Tekan Mulai Pengenalan untuk memberikan izin.")
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        wantRecognition =
            savedInstanceState?.getBoolean(
                "want_recognition",
                true
            ) ?: true
        status = findViewById(R.id.status)
        nominal = findViewById(R.id.nominal)
        toggle = findViewById(R.id.toggle)
        switchCamera = findViewById(R.id.switchCamera)
        val previewContainer =
            findViewById<FrameLayout>(R.id.previewContainer)

        preview = PreviewView(this).apply {
            importantForAccessibility =
                View.IMPORTANT_FOR_ACCESSIBILITY_NO

            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }

        previewContainer.addView(preview, 0)
        try { config = AppConfig.load(this)
            findViewById<RoiOverlay>(R.id.roi).config = config
        }
        catch (_: Exception) { wantRecognition = false
            stopped("Konfigurasi aplikasi tidak valid.")
        }
        switchCamera.isEnabled = false
        if (!wantRecognition && config != null) stopped("Pengenalan dihentikan")
        switchCamera.setOnClickListener {
            session?.switchCamera()
        }
        toggle.setOnClickListener {
            if (session != null || wantRecognition) {
                wantRecognition = false
                stopSession()
                stopped("Pengenalan dihentikan")
            } else {
                wantRecognition = true; requestOrStart()
            }
        }
        preview.addOnLayoutChangeListener { _, l, t, r, b, oldL, oldT, oldR, oldB ->
            if (r - l != oldR - oldL || b - t != oldB - oldT) {
                // Rebuild the shared viewport after resizing or multi-window changes.
                stopSession(); maybeStart()
            }
        }
    }
    override fun onStart() {
        super.onStart()
        foreground = true; if (wantRecognition) requestOrStart()
    }
    override fun onStop() {
        foreground = false
        stopSession(); super.onStop()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("want_recognition", wantRecognition)
        super.onSaveInstanceState(outState)
    }
    private fun requestOrStart() {
        if (!foreground || config == null || permissionPending)
            return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            maybeStart()
            return
        }
        if (requestedBefore && !shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
            wantRecognition = false
            stopped("Aktifkan izin kamera di setelan aplikasi, lalu tekan Mulai Pengenalan.")
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        } else {
            requestedBefore = true; permissionPending = true
            permission.launch(Manifest.permission.CAMERA)
        }
    }
    private fun maybeStart() {
        val cfg = config ?: return
        if (!foreground || !wantRecognition || session != null || preview.width == 0 || preview.height == 0) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        toggle.setText(R.string.stop)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        session = RecognitionSession(this, this, preview, cfg, { message, label, front, cameraReady ->
            val cameraName = if (front) "depan" else "belakang"
            val text = "Status: $message • Kamera $cameraName"
            if (status.text.toString() != text) status.text = text
            val result = if (label == null) getString(R.string.empty_nominal)
                else "Nominal: Rp${NumberFormat.getIntegerInstance(Locale("id", "ID")).format(label.toInt())}"
            if (nominal.text.toString() != result) nominal.text = result
            switchCamera.isEnabled = cameraReady
            switchCamera.contentDescription = if (front) "Ganti ke kamera belakang" else "Ganti ke kamera depan"
        }, { message ->
            session = null; wantRecognition = false
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            stopped(message)
        })
    }
    private fun stopSession() {
        session?.close(); session = null
        switchCamera.isEnabled = false
        nominal.setText(R.string.empty_nominal)
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    private fun stopped(message: String) {
        status.text = "Status: $message"; nominal.setText(R.string.empty_nominal)
        toggle.setText(R.string.start); switchCamera.isEnabled = false
    }
}
