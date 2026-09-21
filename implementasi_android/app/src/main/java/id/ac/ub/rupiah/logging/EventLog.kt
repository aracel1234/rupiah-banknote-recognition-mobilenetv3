package id.ac.ub.rupiah.logging

import android.content.Context
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.io.File

/** Small bounded local JSONL; no images, network, or shared-storage permission. */
class EventLog(context: Context, private val enabled: Boolean) {
    private val file = File(context.filesDir, "events.jsonl")
    private var lastFrame = 0L
    @Synchronized fun event(name: String, vararg data: Pair<String, Any?>) {
        if (!enabled) return
        try {
            if (file.length() > 1024 * 1024) {
                val previous = File(file.parentFile, "events.previous.jsonl")
                previous.delete(); file.renameTo(previous)
            }
            val row = JSONObject().put("event", name).put("elapsed_ms", SystemClock.elapsedRealtime())
                .put("wall_time_ms", System.currentTimeMillis())
            data.forEach { row.put(it.first, it.second ?: JSONObject.NULL) }
            file.appendText(row.toString() + "\n")
        } catch (e: Exception) { Log.w("Rupiah", "Local log unavailable", e) }
    }
    @Synchronized fun frame(vararg data: Pair<String, Any?>) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastFrame >= 1000) { lastFrame = now; event("frame_summary", *data) }
    }
}
