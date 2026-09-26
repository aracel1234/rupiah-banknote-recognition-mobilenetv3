package id.ac.ub.rupiah.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import id.ac.ub.rupiah.R
import id.ac.ub.rupiah.config.AppConfig
import id.ac.ub.rupiah.session.RecognitionSession
import id.ac.ub.rupiah.speech.SpeechOutput
import id.ac.ub.rupiah.logging.EventLog
import java.text.NumberFormat
import java.util.Locale

class MainActivity : ComponentActivity() {

    private lateinit var status: TextView
    private lateinit var nominal: TextView
    private lateinit var toggle: Button
    private lateinit var switchCamera: Button
    private lateinit var preview: PreviewView

    private var speech: SpeechOutput? = null
    private var log: EventLog? = null
    private var config: AppConfig? = null
    private var session: RecognitionSession? = null
    private var foreground = false
    private var wantRecognition = true
    private var permissionPending = false
    private var requestedBefore = false
    private val rupiahFormat = NumberFormat.getIntegerInstance(Locale("id", "ID"))

    private val permission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            permissionPending = false

            if (granted) {
                wantRecognition = true
                maybeStart()
            } else {
                wantRecognition = false
                stopped(
                    "Izin kamera diperlukan. Tekan Mulai Pengenalan untuk memberikan izin."
                )
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        wantRecognition =
            savedInstanceState?.getBoolean("want_recognition", true) ?: true

        requestedBefore = savedInstanceState?.getBoolean("requested_before", false) ?: false
        status = findViewById(R.id.status)
        nominal = findViewById(R.id.nominal)
        toggle = findViewById(R.id.toggle)
        switchCamera = findViewById(R.id.switchCamera)
        preview = findViewById(R.id.preview)

        try {
            config = AppConfig.load(this)
            log = EventLog(this, config!!.logging)
            findViewById<RoiOverlay>(R.id.roi).config = config
        } catch (e: Exception) {
            wantRecognition = false
            stopped("Konfigurasi aplikasi tidak valid.")
        }

        switchCamera.isEnabled = false
        describe(toggle, "Pengenalan belum aktif. Mulai pengenalan.")
        describe(switchCamera, "Ganti Kamera. Tersedia setelah pengenalan dimulai.")

        if (!wantRecognition && config != null) {
            stopped("Pengenalan dihentikan")
        }

        switchCamera.setOnClickListener {
            session?.switchCamera()
        }

        toggle.setOnClickListener {
            if (session != null || wantRecognition) {
                wantRecognition = false
                stopSession()
                stopped("Pengenalan dihentikan")
                speech?.say("Pengenalan dihentikan. Kamera dinonaktifkan.")
            } else {
                wantRecognition = true
                requestOrStart()
            }
        }

        preview.addOnLayoutChangeListener { _, l, t, r, b, oldL, oldT, oldR, oldB ->
            if (r - l != oldR - oldL || b - t != oldB - oldT) {
                // Rebuild the shared viewport after resizing or multi-window changes.
                stopSession()
                maybeStart()
            }
        }
    }

    override fun onStart() {
        super.onStart()
        foreground = true
        ensureSpeech()

        if (wantRecognition) {
            requestOrStart()
        }
    }

    override fun onStop() {
        foreground = false
        stopSession()
        speech?.close()
        speech = null
        super.onStop()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean("want_recognition", wantRecognition)
        outState.putBoolean("requested_before", requestedBefore)
        super.onSaveInstanceState(outState)
    }

    private fun ensureSpeech() {
        val eventLog = log ?: return
        if (speech != null) return
        speech = SpeechOutput(this, status, eventLog,
            { error ->
                if (foreground) {
                    if (error == null) maybeStart() else outputFailed(error)
                }
            },
            { outputFailed("Suara tidak dapat diputar. Periksa setelan Text-to-Speech lalu mulai kembali.") }
        )
    }

    private fun outputFailed(message: String) {
        if (!foreground) return
        wantRecognition = false
        stopSession()
        stopped(message)
    }

    private fun describe(view: Button, text: String) {
        if (view.contentDescription?.toString() != text) view.contentDescription = text
    }

    private fun requestOrStart() {
        if (!foreground || config == null || permissionPending) return
        ensureSpeech()
        speech?.retry()

        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            maybeStart()
            return
        }

        if (
            requestedBefore &&
            !shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)
        ) {
            wantRecognition = false

            stopped(
                "Aktifkan izin kamera di setelan aplikasi, lalu tekan Mulai Pengenalan."
            )

            startActivity(
                Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:$packageName")
                )
            )
        } else {
            requestedBefore = true
            permissionPending = true
            permission.launch(Manifest.permission.CAMERA)
        }
    }

    private fun maybeStart() {
        val cfg = config ?: return
        val output = speech ?: return
        val eventLog = log ?: return

        if (
            !foreground ||
            !output.isReady ||
            !wantRecognition ||
            session != null ||
            preview.width == 0 ||
            preview.height == 0
        ) {
            return
        }

        if (
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.CAMERA
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        describe(toggle, "Pengenalan sedang disiapkan.")
        toggle.setText(R.string.stop)

        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        )

        session = RecognitionSession(
            this,
            this,
            preview,
            cfg,
            output,
            eventLog,
            { message, label, front, cameraReady ->
                val cameraName =
                    if (front) "depan" else "belakang"

                val text =
                    "Status: $message • Kamera $cameraName"

                if (status.text.toString() != text) {
                    status.text = text
                }

                val result =
                    if (label == null) {
                        getString(R.string.empty_nominal)
                    } else {
                        "Nominal: Rp${
                            rupiahFormat.format(label.toInt())
                        }"
                    }

                if (nominal.text.toString() != result) {
                    nominal.text = result
                }

                switchCamera.isEnabled = cameraReady
                val nextCamera = if (front) "belakang" else "depan"
                describe(switchCamera, if (cameraReady) {
                    "Kamera $cameraName aktif. Ganti ke kamera $nextCamera."
                } else "Ganti Kamera. Kamera sedang disiapkan.")
                describe(toggle, if (cameraReady) {
                    "Pengenalan aktif. Hentikan pengenalan."
                } else "Pengenalan sedang disiapkan.")
            },
            { message ->
                session = null
                wantRecognition = false

                window.clearFlags(
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                )

                stopped(message)
                output.say(message)
            }
        )
    }

    private fun stopSession() {
        session?.close()
        session = null

        switchCamera.isEnabled = false

        nominal.setText(
            R.string.empty_nominal
        )

        window.clearFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        )
    }

    private fun stopped(message: String) {
        status.text = "Status: $message"

        nominal.setText(
            R.string.empty_nominal
        )

        describe(toggle, "Pengenalan berhenti. Mulai pengenalan.")
        describe(switchCamera, "Ganti Kamera. Tersedia setelah pengenalan dimulai.")
        toggle.setText(R.string.start)

        switchCamera.isEnabled = false
    }
}