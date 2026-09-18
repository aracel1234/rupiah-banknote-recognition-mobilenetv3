package id.ac.ub.rupiahbenchmark

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter
import java.io.File
import java.io.FileInputStream
import java.io.FileWriter
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel
import java.security.MessageDigest
import java.util.Locale
import kotlin.concurrent.thread
import kotlin.math.roundToInt

class BenchmarkActivity : AppCompatActivity() {
    companion object {
        private const val THREADS = 4
        private const val INPUT_FLOATS = 224 * 224 * 3
        private const val OUTPUTS = 8
        private val CANDIDATES = listOf("fp32", "fp16", "dynamic_range", "full_int8")
    }

    private lateinit var status: TextView
    @Volatile private var preparedCandidate: String? = null
    @Volatile private var preparedInputs: List<ByteBuffer>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply { textSize = 18f; setPadding(32, 32, 32, 32) }
        setContentView(status)
        dispatch(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        dispatch(intent)
    }

    private fun dispatch(intent: Intent) {
        val mode = intent.getStringExtra("mode") ?: "idle"
        val candidate = intent.getStringExtra("candidate") ?: ""
        val session = intent.getIntExtra("session", 0)
        status.text = "mode=$mode candidate=$candidate session=$session"
        when (mode) {
            "stage6_verify" -> background(::stage6Verify)
            "stage7_smoke" -> background(::stage7Smoke)
            "latency" -> background { latency(candidate, session) }
            "memory_baseline" -> background { memoryBaseline(candidate, session) }
            "memory_active" -> background { memoryActive(candidate, session) }
            else -> status.text = "Ready"
        }
    }

    private fun background(block: () -> Unit) = thread {
        try {
            block()
        } catch (e: Throwable) {
            resultFile("last_error.txt").writeText(e.stackTraceToString())
            runOnUiThread { status.text = "ERROR\n${e.message}" }
        }
    }

    private fun resultDir() = File(getExternalFilesDir(null), "results").apply { mkdirs() }
    private fun resultFile(name: String) = File(resultDir(), name)
    private fun marker(name: String) = resultFile(name).writeText("ok\n")
    private fun jsonAsset(path: String) = JSONObject(assets.open(path).bufferedReader().use { it.readText() })

    private fun floatAsset(path: String): FloatArray {
        val bytes = assets.open(path).use { it.readBytes() }
        require(bytes.size == INPUT_FLOATS * 4) { "Ukuran tensor $path salah: ${bytes.size}" }
        return FloatArray(INPUT_FLOATS).also {
            ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(it)
        }
    }

    private fun modelBuffer(path: String): ByteBuffer = assets.openFd(path).use { afd ->
        FileInputStream(afd.fileDescriptor).channel.use {
            it.map(FileChannel.MapMode.READ_ONLY, afd.startOffset, afd.declaredLength)
        }
    }

    private fun options() = Interpreter.Options().setNumThreads(THREADS).setUseXNNPACK(true).setUseNNAPI(false)
    private fun dtype(type: DataType) = if (type == DataType.FLOAT32) "float32" else if (type == DataType.INT8) "int8" else type.toString().lowercase()
    private fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private fun assetHash(path: String) = sha256(assets.open(path).use { it.readBytes() })

    private fun candidateSpec(spec: JSONObject, candidate: String): JSONObject {
        val rows = spec.getJSONArray("candidates")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            if (row.getString("candidate") == candidate) return row
        }
        error("Candidate tidak ditemukan: $candidate")
    }

    private fun inputBuffer(values: FloatArray, spec: JSONObject): ByteBuffer {
        if (spec.getString("input_dtype") != "int8") {
            return ByteBuffer.allocateDirect(INPUT_FLOATS * 4).order(ByteOrder.nativeOrder()).apply {
                values.forEach { putFloat(it) }; rewind()
            }
        }
        val q = spec.getJSONArray("input_quantization")
        val scale = q.getDouble(0).toFloat()
        val zero = q.getInt(1)
        require(scale > 0f)
        return ByteBuffer.allocateDirect(INPUT_FLOATS).order(ByteOrder.nativeOrder()).apply {
            values.forEach { put((it / scale + zero).roundToInt().coerceIn(-128, 127).toByte()) }
            rewind()
        }
    }

    private fun outputBuffer(dtype: String) = ByteBuffer.allocateDirect(if (dtype == "int8") OUTPUTS else OUTPUTS * 4).order(ByteOrder.nativeOrder())

    private fun runOnce(interpreter: Interpreter, input: ByteBuffer, output: ByteBuffer) {
        input.rewind(); output.clear(); interpreter.run(input, output)
    }

    private fun realOutput(output: ByteBuffer, spec: JSONObject): FloatArray {
        output.rewind()
        if (spec.getString("output_dtype") != "int8") return FloatArray(OUTPUTS) { output.float }
        val q = spec.getJSONArray("output_quantization")
        val scale = q.getDouble(0).toFloat()
        val zero = q.getInt(1)
        return FloatArray(OUTPUTS) { scale * (output.get().toInt() - zero) }
    }

    private fun checkContract(interpreter: Interpreter, spec: JSONObject) {
        val input = interpreter.getInputTensor(0)
        val output = interpreter.getOutputTensor(0)
        require(input.shape().contentEquals(intArrayOf(1, 224, 224, 3))) { "Input shape salah" }
        require(output.shape().contentEquals(intArrayOf(1, 8))) { "Output shape salah" }
        require(dtype(input.dataType()) == spec.getString("input_dtype")) { "Input dtype salah" }
        require(dtype(output.dataType()) == spec.getString("output_dtype")) { "Output dtype salah" }
    }

    private fun openInterpreter(base: String, spec: JSONObject): Interpreter {
        val path = "$base/${spec.getString("file_name")}"
        require(assetHash(path) == spec.getString("model_sha256")) { "Hash model berbeda" }
        val interpreter = Interpreter(modelBuffer(path), options())
        try {
            interpreter.allocateTensors()
            checkContract(interpreter, spec)
            return interpreter
        } catch (e: Throwable) {
            interpreter.close()
            throw e
        }
    }

    private fun stage6Verify() {
        val base = "stage6"
        val spec = jsonAsset("$base/android_verification_spec.json")
        val inputName = spec.getString("input_file")
        require(assetHash("$base/$inputName") == spec.getString("input_sha256"))
        val className = spec.getString("class_names_file")
        require(assetHash("$base/$className") == spec.getString("class_names_sha256"))
        val classes = JSONArray(assets.open("$base/$className").bufferedReader().use { it.readText() })
        require(classes.length() == OUTPUTS)
        val values = floatAsset("$base/$inputName")
        val rows = JSONArray()

        for (candidate in CANDIDATES) {
            val c = candidateSpec(spec, candidate)
            val row = JSONObject().put("candidate", candidate).put("passed", false)
            var interpreter: Interpreter? = null
            try {
                interpreter = openInterpreter(base, c)
                val output = outputBuffer(c.getString("output_dtype"))
                runOnce(interpreter, inputBuffer(values, c), output)
                val result = realOutput(output, c)
                require(result.all { it.isFinite() })
                val pred = result.indices.maxBy { result[it] }
                val labelOk = pred in 0 until classes.length() && classes.getString(pred).isNotBlank()
                row.put("model_sha256", c.getString("model_sha256"))
                    .put("input_shape", JSONArray(interpreter.getInputTensor(0).shape().toList()))
                    .put("output_shape", JSONArray(interpreter.getOutputTensor(0).shape().toList()))
                    .put("input_dtype", dtype(interpreter.getInputTensor(0).dataType()))
                    .put("output_dtype", dtype(interpreter.getOutputTensor(0).dataType()))
                    .put("output_count", result.size).put("finite_output", true)
                    .put("label_mapping_ok", labelOk).put("predicted_index", pred)
                    .put("predicted_label", classes.getString(pred)).put("passed", labelOk)
            } catch (e: Throwable) {
                row.put("error", e.message ?: e.javaClass.simpleName)
            } finally {
                interpreter?.close()
                row.put("interpreter_closed", interpreter != null)
                rows.put(row)
            }
        }
        val passed = (0 until rows.length()).all { rows.getJSONObject(it).optBoolean("passed") && rows.getJSONObject(it).optBoolean("interpreter_closed") }
        resultFile("stage6_android_verification.json").writeText(JSONObject()
            .put("stage", 6).put("bundle_id", spec.getString("bundle_id"))
            .put("class_names_sha256", spec.getString("class_names_sha256"))
            .put("android_version", android.os.Build.VERSION.RELEASE).put("device_model", android.os.Build.MODEL)
            .put("candidates", rows).put("all_passed", passed).toString(2))
        marker("stage6_verify.done")
        runOnUiThread { status.text = "Stage 6 Android verification: ${if (passed) "PASS" else "FAIL"}" }
    }

    private fun stage7Spec() = jsonAsset("stage7/benchmark_spec.json")

    private fun stage7Smoke() {
        val spec = stage7Spec()
        val lines = assets.open("stage7/inputs_manifest.csv").bufferedReader().use { it.readLines() }
        require(lines.size == spec.getInt("input_count") + 1) { "inputs_manifest tidak berjumlah 80" }
        val header = lines.first().split(',')
        val fileCol = header.indexOf("file_name")
        val shaCol = header.indexOf("sha256")
        require(fileCol >= 0 && shaCol >= 0)
        lines.drop(1).forEach {
            val cols = it.split(',')
            require(assetHash("stage7/${cols[fileCol]}") == cols[shaCol]) { "Hash input benchmark berubah" }
        }
        val input = floatAsset("stage7/input_000.f32")
        val rows = JSONArray()
        for (candidate in CANDIDATES) {
            val c = candidateSpec(spec, candidate)
            var passed = false
            var message = ""
            var interpreter: Interpreter? = null
            try {
                interpreter = openInterpreter("stage7", c)
                val output = outputBuffer(c.getString("output_dtype"))
                runOnce(interpreter, inputBuffer(input, c), output)
                passed = realOutput(output, c).all { it.isFinite() }
                message = if (passed) "ok" else "output invalid"
            } catch (e: Throwable) {
                message = e.message ?: e.javaClass.simpleName
            } finally {
                interpreter?.close()
            }
            rows.put(JSONObject().put("candidate", candidate).put("passed", passed).put("message", message))
        }
        val passed = (0 until rows.length()).all { rows.getJSONObject(it).getBoolean("passed") }
        resultFile("stage7_smoke_report.json").writeText(JSONObject().put("stage", 7).put("all_passed", passed).put("candidates", rows).toString(2))
        marker("stage7_smoke.done")
        runOnUiThread { status.text = "Stage 7 smoke: ${if (passed) "PASS" else "FAIL"}" }
    }

    private fun inputs(candidate: String): List<ByteBuffer> {
        preparedInputs?.let { if (preparedCandidate == candidate) return it }
        val spec = stage7Spec()
        val c = candidateSpec(spec, candidate)
        return (0 until spec.getInt("input_count")).map {
            inputBuffer(floatAsset("stage7/input_${it.toString().padStart(3, '0')}.f32"), c)
        }.also { preparedCandidate = candidate; preparedInputs = it }
    }

    private fun latency(candidate: String, session: Int) {
        require(candidate in CANDIDATES && session in 1..5)
        val spec = stage7Spec()
        val c = candidateSpec(spec, candidate)
        val prepared = inputs(candidate)
        val modelPath = "stage7/${c.getString("file_name")}"
        require(assetHash(modelPath) == c.getString("model_sha256")) { "Hash model berbeda" }
        val startInit = SystemClock.elapsedRealtimeNanos()
        val interpreter = Interpreter(modelBuffer(modelPath), options())
        interpreter.allocateTensors()
        val endInit = SystemClock.elapsedRealtimeNanos()
        checkContract(interpreter, c)
        val output = outputBuffer(c.getString("output_dtype"))
        val startFirst = SystemClock.elapsedRealtimeNanos()
        runOnce(interpreter, prepared[0], output)
        val endFirst = SystemClock.elapsedRealtimeNanos()
        repeat(spec.getInt("warmup_latency")) { runOnce(interpreter, prepared[it % prepared.size], output) }

        val rows = StringBuilder()
        fun add(type: String, index: Int, tensor: Int?, ms: Double) {
            rows.append(candidate).append(',').append(c.getString("model_sha256")).append(',').append(session)
                .append(',').append(type).append(',').append(index).append(',').append(tensor ?: "")
                .append(',').append("%.9f".format(Locale.US, ms)).append('\n')
        }
        add("initialization", 1, null, (endInit - startInit) / 1e6)
        add("first_inference", 1, 0, (endFirst - startFirst) / 1e6)
        repeat(spec.getInt("stable_inference_per_session")) {
            val tensor = it % prepared.size
            val start = SystemClock.elapsedRealtimeNanos()
            runOnce(interpreter, prepared[tensor], output)
            add("stable", it + 1, tensor, (SystemClock.elapsedRealtimeNanos() - start) / 1e6)
        }
        interpreter.close()
        val csv = resultFile("stage7_latency.csv")
        synchronized(BenchmarkActivity::class.java) {
            if (!csv.exists()) csv.writeText("candidate,model_sha256,session,measurement_type,index,tensor_index,time_ms\n")
            FileWriter(csv, true).use { it.write(rows.toString()) }
        }
        marker("latency_${candidate}_${session}.done")
        runOnUiThread { status.text = "Latency $candidate session $session selesai" }
    }

    private fun memoryBaseline(candidate: String, session: Int) {
        require(candidate in CANDIDATES && session in 1..5)
        inputs(candidate)
        marker("baseline_${candidate}_${session}.ready")
        runOnUiThread { status.text = "Baseline ready: $candidate session $session" }
    }

    private fun memoryActive(candidate: String, session: Int) {
        require(candidate in CANDIDATES && session in 1..5)
        val spec = stage7Spec()
        val c = candidateSpec(spec, candidate)
        val prepared = inputs(candidate)
        val interpreter = openInterpreter("stage7", c)
        val output = outputBuffer(c.getString("output_dtype"))
        repeat(spec.getInt("memory_warmup")) { runOnce(interpreter, prepared[it % prepared.size], output) }
        marker("active_${candidate}_${session}.ready")
        val end = SystemClock.elapsedRealtimeNanos() + spec.getInt("memory_active_seconds") * 1_000_000_000L
        var i = 0
        while (SystemClock.elapsedRealtimeNanos() < end) runOnce(interpreter, prepared[(i++) % prepared.size], output)
        marker("active_${candidate}_${session}.done")
        interpreter.close()
        runOnUiThread { status.text = "Memory active selesai: $candidate session $session" }
    }
}
