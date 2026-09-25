package id.ac.ub.rupiah.speech

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import id.ac.ub.rupiah.logging.EventLog
import java.util.Locale

/** All public methods run on main; callbacks from the engine are marshalled onto main. */
class SpeechOutput(
    context: Context,
    private val log: EventLog,
    private val ready: (String?) -> Unit,
    private val failed: () -> Unit
) : AutoCloseable {

    private val main = Handler(Looper.getMainLooper())
    private var engine: TextToSpeech? = null
    private var closed = false
    private var available = false
    private var serial = 0L

    init {
        engine = TextToSpeech(context.applicationContext) { code ->
            main.post {
                initialize(code)
            }
        }
    }

    private fun initialize(code: Int) {
        if (closed) return

        val tts = engine ?: return

        if (code != TextToSpeech.SUCCESS) {
            ready("Mesin suara tidak tersedia. Periksa setelan Text-to-Speech.")
            return
        }

        try {
            val language = tts.setLanguage(Locale("id", "ID"))

            val voice = tts.voices
                ?.filter {
                    it.locale.language in setOf("id", "in", "ind") &&
                            !it.isNetworkConnectionRequired &&
                            it.features?.contains(
                                TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED
                            ) != true
                }
                ?.sortedBy { it.name }
                ?.firstOrNull()

            if (
                language < TextToSpeech.LANG_AVAILABLE ||
                voice == null ||
                tts.setVoice(voice) != TextToSpeech.SUCCESS
            ) {
                ready(
                    "Pasang suara Bahasa Indonesia luring di setelan Text-to-Speech, lalu mulai kembali."
                )
                return
            }

            tts.setSpeechRate(1f)

            tts.setOnUtteranceProgressListener(
                object : UtteranceProgressListener() {

                    override fun onStart(id: String?) {
                        log.event(
                            "tts_start",
                            "utterance_id" to id
                        )
                    }

                    override fun onDone(id: String?) {
                        log.event(
                            "tts_done",
                            "utterance_id" to id
                        )
                    }

                    @Deprecated("Platform callback")
                    override fun onError(id: String?) {
                        error(id)
                    }

                    override fun onError(id: String?, errorCode: Int) {
                        error(id)
                    }

                    private fun error(id: String?) {
                        log.event(
                            "tts_error",
                            "utterance_id" to id
                        )

                        main.post {
                            if (!closed) {
                                available = false
                                failed()
                            }
                        }
                    }
                }
            )

            available = true

            log.event(
                "tts_ready",
                "voice" to voice.name,
                "network_required" to false
            )

            ready(null)
        } catch (e: Exception) {
            ready(
                "Suara luring belum siap. Periksa setelan Text-to-Speech."
            )
        }
    }

    fun camera(front: Boolean) =
        say(
            if (front) {
                "Kamera depan aktif"
            } else {
                "Kamera belakang aktif"
            }
        )

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

        return say(text)
    }

    fun say(text: String): Boolean {
        if (closed || !available) return false

        return try {
            val id = "rupiah-${++serial}"

            val ok =
                engine?.speak(
                    text,
                    TextToSpeech.QUEUE_FLUSH,
                    null,
                    id
                ) == TextToSpeech.SUCCESS

            log.event(
                "tts_request",
                "utterance_id" to id,
                "text" to text,
                "accepted" to ok
            )

            ok
        } catch (e: Exception) {
            false
        }
    }

    fun stop() {
        engine?.stop()
    }

    override fun close() {
        closed = true
        available = false
        engine?.stop()
        engine?.shutdown()
        engine = null
    }
}