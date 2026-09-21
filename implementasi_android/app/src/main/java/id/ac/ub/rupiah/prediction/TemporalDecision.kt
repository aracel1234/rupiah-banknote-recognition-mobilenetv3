package id.ac.ub.rupiah.prediction

import id.ac.ub.rupiah.config.AppConfig
import java.util.ArrayDeque

/** Time-window averaging of complete score vectors, never majority vote. Single worker only. */
class TemporalDecision(private val config: AppConfig, private val labels: List<String>) {
    private data class Entry(val time: Long, val scores: FloatArray)
    data class Result(val label: String?, val status: String, val announce: Boolean = false)
    private val window = ArrayDeque<Entry>()
    private var rejectedSince: Long? = null
    private var announced: String? = null
    private var lastObservation: Long? = null
    fun reset() { window.clear(); rejectedSince = null; announced = null; lastObservation = null }
    private fun observe(now: Long) {
        if (lastObservation != null && now - lastObservation!! > config.windowMs) {
            window.clear(); rejectedSince = null
        }
        lastObservation = now
        while (!window.isEmpty() && now - window.first.time > config.windowMs) window.removeFirst()
    }
    fun reject(now: Long, status: String): Result {
        observe(now)
        window.clear() // Never reuse accepted evidence across an invalid image.
        if (rejectedSince == null) rejectedSince = now
        if (now - rejectedSince!! >= config.windowMs) announced = null
        return Result(null, status)
    }
    fun accept(scores: FloatArray, now: Long): Result {
        observe(now)
        val winner = scores.indices.maxByOrNull { scores[it] }!!
        if (labels[winner] == "nonuang" || scores[winner] < config.threshold) return reject(now, "Uang belum dapat dikenali")
        rejectedSince = null
        window.addLast(Entry(now, scores.copyOf()))
        if (window.size < config.minimumResults) return Result(null, "Tahan posisi uang")
        val mean = FloatArray(labels.size)
        for (item in window) for (i in mean.indices) mean[i] += item.scores[i] / window.size
        val best = mean.indices.maxByOrNull { mean[it] }!!
        if (labels[best] == "nonuang" || mean[best] < config.threshold || best != winner) return Result(null, "Tahan posisi uang")
        val label = labels[best]
        return Result(label, "Nominal dikenali", label != announced)
    }
    /** Mark only after TextToSpeech.speak accepted the request. */
    fun markAnnounced(label: String) { announced = label }
}
