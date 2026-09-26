package id.ac.ub.rupiah.speech

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.view.View
import android.view.accessibility.AccessibilityManager
import id.ac.ub.rupiah.logging.EventLog
import java.util.Locale

/** Main thread only. Screen reader owns speech while touch exploration is active. */
class SpeechOutput(
    context: Context,
    private val announcementHost: View,
    private val log: EventLog,
    private val ready: (String?) -> Unit,
    private val failed: () -> Unit
) : AutoCloseable {
    private val app = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val accessibility = app.getSystemService(Context.ACCESSIBILITY_SERVICE)
            as AccessibilityManager
    private var engine: TextToSpeech? = null
    private var closed = false
    private var generation = 0
    private var serial = 0L
    private var pending: String? = null
    private var initializing = false
    private var reader = false
    var isReady = false
        private set
    val route: String get() = if (reader) "accessibility_announcement" else "offline_tts"

    private val listener = AccessibilityManager.TouchExplorationStateChangeListener {
        main.post { if (!closed) selectRoute() }
    }

    init {
        accessibility.addTouchExplorationStateChangeListener(listener)
        // Post so the owner's SpeechOutput property is assigned before ready().
        main.post { if (!closed && generation == 0) selectRoute(force = true) }
    }

    private fun selectRoute(force: Boolean = false) {
        val next = accessibility.isEnabled && accessibility.isTouchExplorationEnabled
        if (!force && next == reader) return
        stop()
        generation++
        engine?.shutdown()
        engine = null
        isReady = false
        initializing = false
        reader = next
        log.event("speech_route", "route" to route)
        if (reader) {
            isReady = true
            ready(null)
        } else {
            val token = generation
            initializing = true
            try {
                engine = TextToSpeech(app) { code ->
                    main.post {
                        if (!closed && token == generation) initialize(code, token)
                    }
                }
            } catch (_: Exception) {
                initializing = false
                ready("Mesin suara tidak tersedia. Periksa setelan Text-to-Speech.")
            }
        }
    }

    private fun initialize(code: Int, token: Int) {
        initializing = false
        val tts = engine ?: return
        try {
            check(code == TextToSpeech.SUCCESS)
            check(tts.setLanguage(Locale("id", "ID")) >= TextToSpeech.LANG_AVAILABLE)
            val voice = tts.voices?.filter {
                it.locale.language in setOf("id", "in", "ind") &&
                        !it.isNetworkConnectionRequired &&
                        it.features?.contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) != true
            }?.minByOrNull { it.name }
            check(voice != null && tts.setVoice(voice) == TextToSpeech.SUCCESS)
            tts.setSpeechRate(1f)
            tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                private fun record(event: String, id: String?) {
                    main.post {
                        if (!closed && token == generation) {
                            log.event(event, "utterance_id" to id)
                            if (event == "tts_error") {
                                isReady = false
                                failed()
                            }
                        }
                    }
                }
                override fun onStart(id: String?) = record("tts_start", id)
                override fun onDone(id: String?) = record("tts_done", id)
                override fun onStop(id: String?, interrupted: Boolean) = record("tts_stop", id)
                @Deprecated("Platform callback")
                override fun onError(id: String?) = record("tts_error", id)
                override fun onError(id: String?, errorCode: Int) = record("tts_error", id)
            })
            isReady = true
            log.event("tts_ready", "voice" to voice.name, "network_required" to false)
            val queued = pending
            pending = null
            ready(null)
            if (queued != null && !closed && !say(queued)) failed()
        } catch (_: Exception) {
            pending = null
            ready("Pasang suara Bahasa Indonesia luring di setelan Text-to-Speech, lalu mulai kembali.")
        }
    }

    fun camera(front: Boolean, starting: Boolean): Boolean {
        val current = if (front) "depan" else "belakang"
        return say(if (starting) {
            "Memulai pengenalan. Kamera $current aktif."
        } else {
            "Kamera $current aktif."
        })
    }

    fun nominal(label: String): Boolean {
        val text = when (label) {
            "1000" -> "Seribu rupiah"
            "2000" -> "Dua ribu rupiah"
            "5000" -> "Lima ribu rupiah"
            "10000" -> "Sepuluh ribu rupiah"
            "20000" -> "Dua puluh ribu rupiah"
            "50000" -> "Lima puluh ribu rupiah"
            "100000" -> "Seratus ribu rupiah"
            else -> return false
        }
        return say(text, interrupt = false)
    }

    /** True means a request was accepted, not that the user heard it. */
    fun say(text: String, interrupt: Boolean = true): Boolean {
        if (closed) return false
        selectRoute() // Guard against a service change before listener delivery.
        if (!isReady) {
            if (!initializing) return false
            pending = text // At most one pending message during engine initialization.
            return true
        }
        val id = "rupiah-${++serial}"
        if (reader) {
            if (!announcementHost.isShown || !announcementHost.isAttachedToWindow) return false
            // No extra visible/hidden widget and no second TTS engine.
            // Supported on the target Android 14 device. Deprecated from API 36:
            // delivery and ordering remain controlled by the accessibility service.
            @Suppress("DEPRECATION")
            announcementHost.announceForAccessibility(text)
            log.event("a11y_output_requested", "utterance_id" to id,
                "text" to text, "route" to route)
            return true
        }
        return try {
            val accepted = engine?.speak(text,
                if (interrupt) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD,
                null, id) == TextToSpeech.SUCCESS
            log.event("tts_request", "utterance_id" to id, "text" to text, "accepted" to accepted)
            accepted
        } catch (_: Exception) { false }
    }

    fun retry() {
        if (!closed && !isReady && !initializing) selectRoute(force = true)
    }

    fun stop() {
        pending = null
        engine?.stop()
        // A service-owned utterance already being spoken cannot be cancelled here.
    }

    override fun close() {
        if (closed) return
        closed = true
        generation++
        accessibility.removeTouchExplorationStateChangeListener(listener)
        stop()
        engine?.shutdown()
        engine = null
        isReady = false
    }
}
