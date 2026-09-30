package id.ac.ub.rupiah.testing

import android.os.SystemClock

/**
 * Instrumentasi pasif untuk pengujian Bab 6.
 *
 * Komponen ini hanya mencatat identitas percobaan dan timestamp. Komponen tidak
 * mengubah citra, keputusan QualityGate, skor model, TemporalDecision, kamera,
 * maupun urutan TTS.
 */
object TestTelemetry {

    data class ContextSnapshot(
        val testId: String?,
        val testGroup: String?,
        val expectedLabel: String?,
        val active: Boolean,
        val armed: Boolean,
        val trialBeginNs: Long?,
        val objectPlacedNs: Long?,
        val t0Ns: Long?,
        val t1Ns: Long?,
        val t2Ns: Long?,
        val stableLabel: String?,
        val nominalUtteranceId: String?,
        val lastStatus: String?,
        val lastScores: String?,
        val lastRejectionReason: String?,
        val frameCount: Long,
        val statusCounts: Map<String, Int>
    ) {
        val decisionMs: Double?
            get() = if (t0Ns != null && t1Ns != null) {
                (t1Ns - t0Ns) / 1_000_000.0
            } else null

        val ttsMs: Double?
            get() = if (t1Ns != null && t2Ns != null) {
                (t2Ns - t1Ns) / 1_000_000.0
            } else null

        val endToEndMs: Double?
            get() = if (t0Ns != null && t2Ns != null) {
                (t2Ns - t0Ns) / 1_000_000.0
            } else null
    }

    private var testId: String? = null
    private var testGroup: String? = null
    private var expectedLabel: String? = null
    private var active = false
    private var armed = false
    private var trialBeginNs: Long? = null
    private var objectPlacedNs: Long? = null

    private var lastObservationNs: Long? = null
    private var t0Ns: Long? = null
    private var t1Ns: Long? = null
    private var t2Ns: Long? = null
    private var stableLabel: String? = null
    private var nominalUtteranceId: String? = null

    private var lastStatus: String? = null
    private var lastScores: String? = null
    private var lastRejectionReason: String? = null
    private var frameCount = 0L
    private val statusCounts = linkedMapOf<String, Int>()

    @Synchronized
    fun begin(id: String, group: String?, expected: String?): Boolean {
        if (active) return false
        val clean = id.trim()
        if (clean.isEmpty()) return false

        testId = clean
        testGroup = group?.trim()?.takeIf { it.isNotEmpty() }
        expectedLabel = expected?.trim()?.takeIf { it.isNotEmpty() }
        active = true
        armed = false
        trialBeginNs = SystemClock.elapsedRealtimeNanos()
        objectPlacedNs = null
        clearDecisionSequence(clearObservation = true)
        lastStatus = null
        lastScores = null
        lastRejectionReason = null
        frameCount = 0L
        statusCounts.clear()
        return true
    }

    @Synchronized
    fun arm(): Long? {
        if (!active) return null
        armed = true
        val now = SystemClock.elapsedRealtimeNanos()
        objectPlacedNs = now
        clearDecisionSequence(clearObservation = true)
        lastStatus = null
        lastScores = null
        lastRejectionReason = null
        frameCount = 0L
        statusCounts.clear()
        return now
    }

    /**
     * Dipanggil saat sebuah bingkai benar-benar memasuki FramePreprocessor.
     * Jika jeda antarobservasi melebihi jendela temporal, rangkaian keputusan
     * sebelumnya tidak lagi menjadi dasar keputusan berikutnya.
     */
    @Synchronized
    fun markObservationStart(windowMs: Long) {
        if (!active || !armed || t1Ns != null) return
        val now = SystemClock.elapsedRealtimeNanos()
        val previous = lastObservationNs
        if (previous != null && now - previous > windowMs * 1_000_000L) {
            clearDecisionSequence(clearObservation = false)
        }
        lastObservationNs = now
    }

    /**
     * t0 dicatat tepat setelah QualityGate menerima ROI dan sebelum konversi RGB
     * serta resize. Hanya t0 pertama pada rangkaian keputusan yang dipertahankan.
     */
    @Synchronized
    fun markQualityPassed(): Long? {
        if (!active || !armed || t1Ns != null) return t0Ns
        if (t0Ns == null) t0Ns = SystemClock.elapsedRealtimeNanos()
        return t0Ns
    }

    @Synchronized
    fun markInferenceStart(): Long? {
        if (!active || !armed || t1Ns != null) return null
        return SystemClock.elapsedRealtimeNanos()
    }

    /**
     * Penolakan sebelum keputusan stabil menghapus dasar waktu keputusan,
     * sama seperti bukti temporal yang tidak boleh digunakan kembali.
     */
    @Synchronized
    fun markDecisionReset(reason: String?) {
        if (!active || !armed || t1Ns != null) return
        lastRejectionReason = reason
        clearDecisionSequence(clearObservation = false)
    }

    /** t1 dicatat segera setelah RecognitionSession melaporkan hasil TemporalDecision stabil. */
    @Synchronized
    fun markStableDecision(label: String): Long? {
        if (!active || !armed || t0Ns == null || t1Ns != null) return t1Ns
        val now = SystemClock.elapsedRealtimeNanos()
        t1Ns = now
        stableLabel = label
        return now
    }

    /** Hanya utterance nominal yang cocok dengan label stabil yang dipasangkan dengan t2. */
    @Synchronized
    fun markNominalRequest(utteranceId: String?, label: String): Boolean {
        if (!active || !armed || t1Ns == null || utteranceId.isNullOrBlank()) return false
        if (stableLabel != null && stableLabel != label) return false
        if (nominalUtteranceId == null) nominalUtteranceId = utteranceId
        return nominalUtteranceId == utteranceId
    }

    /** t2 dicatat langsung pada UtteranceProgressListener.onStart(). */
    @Synchronized
    fun markTtsStart(utteranceId: String?): Long? {
        if (!active || !armed || t1Ns == null || t2Ns != null) return t2Ns
        if (utteranceId.isNullOrBlank() || utteranceId != nominalUtteranceId) return null
        val now = SystemClock.elapsedRealtimeNanos()
        t2Ns = now
        return now
    }

    /** Dipanggil untuk setiap hasil analisis, tetapi tidak melakukan I/O. */
    @Synchronized
    fun observeResult(status: String?, scores: String?, label: String?) {
        if (!active || !armed) return
        frameCount++
        lastStatus = status
        lastScores = scores
        if (!status.isNullOrBlank()) {
            statusCounts[status] = (statusCounts[status] ?: 0) + 1
        }

        when {
            status == "Nominal dikenali" && !label.isNullOrBlank() -> {
                markStableDecision(label)
            }
            status == "Tahan posisi uang" -> Unit
            t1Ns == null -> markDecisionReset(status)
        }
    }

    @Synchronized
    fun matches(id: String?): Boolean =
        active && !id.isNullOrBlank() && testId == id.trim()

    @Synchronized
    fun snapshot(): ContextSnapshot = ContextSnapshot(
        testId = testId,
        testGroup = testGroup,
        expectedLabel = expectedLabel,
        active = active,
        armed = armed,
        trialBeginNs = trialBeginNs,
        objectPlacedNs = objectPlacedNs,
        t0Ns = t0Ns,
        t1Ns = t1Ns,
        t2Ns = t2Ns,
        stableLabel = stableLabel,
        nominalUtteranceId = nominalUtteranceId,
        lastStatus = lastStatus,
        lastScores = lastScores,
        lastRejectionReason = lastRejectionReason,
        frameCount = frameCount,
        statusCounts = statusCounts.toMap()
    )

    @Synchronized
    fun clear() {
        testId = null
        testGroup = null
        expectedLabel = null
        active = false
        armed = false
        trialBeginNs = null
        objectPlacedNs = null
        clearDecisionSequence(clearObservation = true)
        lastStatus = null
        lastScores = null
        lastRejectionReason = null
        frameCount = 0L
        statusCounts.clear()
    }

    private fun clearDecisionSequence(clearObservation: Boolean) {
        if (clearObservation) lastObservationNs = null
        t0Ns = null
        t1Ns = null
        t2Ns = null
        stableLabel = null
        nominalUtteranceId = null
    }
}
