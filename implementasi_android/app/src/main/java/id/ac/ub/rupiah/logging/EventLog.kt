package id.ac.ub.rupiah.logging

import android.content.Context
import android.os.SystemClock
import android.util.Log
import id.ac.ub.rupiah.testing.TestTelemetry
import org.json.JSONObject
import java.io.File

/** Small bounded local JSONL; no images, network, or shared-storage permission. */
class EventLog(
    context: Context,
    private val enabled: Boolean
) {

    private val file = File(context.filesDir, "events.jsonl")
    private val trialFile = File(context.filesDir, "bab6_trials.jsonl")
    private var lastFrame = 0L

    @Synchronized
    fun event(
        name: String,
        vararg data: Pair<String, Any?>
    ) {
        if (!enabled) return

        try {
            if (file.length() > 1024 * 1024) {
                val previous = File(file.parentFile, "events.previous.jsonl")
                previous.delete()
                file.renameTo(previous)
            }

            val nowNs = SystemClock.elapsedRealtimeNanos()
            val trial = TestTelemetry.snapshot()
            val row = JSONObject()
                .put("event", name)
                .put("elapsed_ns", nowNs)
                .put("elapsed_ms", nowNs / 1_000_000L)
                .put("wall_time_ms", System.currentTimeMillis())

            if (trial.active) {
                row.put("test_id", trial.testId ?: JSONObject.NULL)
                row.put("test_group", trial.testGroup ?: JSONObject.NULL)
                row.put("expected_label", trial.expectedLabel ?: JSONObject.NULL)
                row.put("trial_armed", trial.armed)
            }

            data.forEach { (key, value) ->
                row.put(key, value ?: JSONObject.NULL)
            }

            val line = row.toString() + "\n"
            file.appendText(line)

            // Hanya kejadian kontrol trial disalin ke berkas ringkas khusus Bab 6.
            // frame_summary dan log diagnostik tetap berada pada events.jsonl.
            if (name.startsWith("trial_")) {
                trialFile.appendText(line)
            }
        } catch (e: Exception) {
            Log.w("Rupiah", "Local log unavailable", e)
        }
    }

    @Synchronized
    fun frame(
        vararg data: Pair<String, Any?>
    ) {
        val map = data.toMap()
        val status = map["status"] as? String
        val scores = map["scores"] as? String
        val label = map["label"] as? String

        // Dipanggil pada setiap bingkai yang dianalisis, tepat setelah hasil
        // TemporalDecision diperoleh. Tidak ada I/O di TestTelemetry.
        TestTelemetry.observeResult(status, scores, label)

        val now = SystemClock.elapsedRealtime()
        if (now - lastFrame < 1000L) return
        lastFrame = now

        event("frame_summary", *data)
    }
}
