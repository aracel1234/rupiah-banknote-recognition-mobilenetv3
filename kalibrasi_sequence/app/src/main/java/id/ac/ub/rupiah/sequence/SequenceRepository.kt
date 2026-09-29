package id.ac.ub.rupiah.sequence

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

class SequenceRepository(private val context: Context) {
    private val prefs = context.getSharedPreferences("sequence_collector", Context.MODE_PRIVATE)

    /**
     * Alias dataset dikunci ke perangkat penelitian. Nilai ini tidak pernah
     * dibaca dari perangkat runtime dan tidak dapat diubah melalui SharedPreferences.
     */
    val deviceAlias: String
        get() = DeviceIdentity.ALIAS

    init {
        // Bersihkan alias lama (misalnya alias Poco/perangkat lain) agar tidak
        // dapat mengambil alih folder dataset pada instalasi yang pernah dipakai.
        prefs.edit().remove("device_alias").apply()
    }

    var driveTreeUri: Uri?
        get() = prefs.getString("drive_tree_uri", null)?.let(Uri::parse)
        set(value) { prefs.edit().putString("drive_tree_uri", value?.toString()).apply() }

    private fun root(): File = File(context.getExternalFilesDir(null), "sequence_calibration/$deviceAlias").apply { mkdirs() }
    private fun checklistFile() = File(root(), "checklist.json")
    private fun checklistCsvFile() = File(root(), "checklist.csv")
    private fun planFile() = File(root(), "experiment_plan.json")
    private fun manifestJsonlFile() = File(root(), "manifest.jsonl")
    private fun manifestCsvFile() = File(root(), "manifest.csv")
    private fun configFile() = File(root(), "collector_config.json")

    fun ensurePlan(): MutableList<SequenceItem> {
        if (!checklistFile().exists()) {
            val items = SequencePlan.build()
            writeChecklist(items)
            writeExperimentPlan()
            if (!manifestJsonlFile().exists()) manifestJsonlFile().writeText("")
            exportManifestCsv()
            return items
        }
        return loadChecklist()
    }

    fun allItems(): MutableList<SequenceItem> = ensurePlan()
    fun hasSavedSequences(): Boolean = ensurePlan().any { it.status == "SAVED" }
    fun rootDirectory(): File = root()

    fun persistConfirmedConfig(config: SequenceConfig) {
        require(config.confirmed) { "Konfigurasi belum dikonfirmasi" }
        if (hasSavedSequences() && configFile().exists()) {
            val existing = JSONObject(configFile().readText())
            val existingHash = existing.optString("config_sha256")
            require(existingHash == config.sha256()) {
                "Konfigurasi tidak boleh diubah setelah sequence pertama tersimpan"
            }
        }
        val payload = config.toJson().apply {
            put("config_sha256", config.sha256())
            put("locked_for_device_alias", deviceAlias)
            put("locked_at_utc", nowUtc())
        }
        configFile().writeText(payload.toString(2))
    }

    fun validateConfigForRecording(config: SequenceConfig) {
        require(config.confirmed) { "Konfigurasi 5.7.2 belum dikonfirmasi" }
        if (configFile().exists()) {
            val existing = JSONObject(configFile().readText())
            require(existing.optString("config_sha256") == config.sha256()) {
                "Konfigurasi aktif berbeda dari konfigurasi dataset yang sudah dikunci"
            }
        } else {
            persistConfirmedConfig(config)
        }
    }

    fun saveSequence(
        item: SequenceItem,
        config: SequenceConfig,
        modelHash: String,
        records: List<FrameRecord>,
        stats: SequenceRunStats,
        note: String
    ): SavedSequence {
        validateConfigForRecording(config)
        require(item.status != "SAVED") { "Sequence ${item.id} sudah tersimpan" }
        require(records.isNotEmpty()) { "Tidak ada frame yang terekam" }
        require(records.zipWithNext().all { (a, b) -> b.elapsedMs >= a.elapsedMs }) { "Timestamp frame tidak monoton" }

        val rel = relativeDir(item)
        val dir = File(root(), rel).apply { mkdirs() }
        val framesFile = File(dir, "frames.csv")
        val stagesFile = File(dir, "stages.json")
        val metadataFile = File(dir, "metadata.json")
        val configSnapshot = File(dir, "config_snapshot.json")

        writeFramesCsv(framesFile, records)
        writeStagesJson(stagesFile, item)
        configSnapshot.writeText(config.toJson().apply { put("config_sha256", config.sha256()) }.toString(2))

        val now = nowUtc()
        val scoresCount = records.count { it.scores != null }
        val metadata = JSONObject().apply {
            put("schema_version", 1)
            put("sequence_id", item.id)
            put("kind", item.kind.name.lowercase())
            put("scenario", item.scenario)
            put("display_name", item.displayName)
            put("primary_label", item.primaryLabel ?: JSONObject.NULL)
            put("secondary_label", item.secondaryLabel ?: JSONObject.NULL)
            put("captured_at_utc", now)
            put("device_alias", deviceAlias)
            put("device_serial", DeviceIdentity.SERIAL)
            put("device_manufacturer", DeviceIdentity.MANUFACTURER)
            put("device_model", DeviceIdentity.MODEL)
            put("device_device", DeviceIdentity.DEVICE)
            put("android_release", DeviceIdentity.ANDROID_RELEASE)
            put("sdk_int", DeviceIdentity.SDK_INT)
            put("device_abi", DeviceIdentity.ABI)
            put("camera_facing", "back")
            put("controlled_lighting_lux", "350-450")
            put("baseline_distance_cm", 20)
            put("camera_control", "automatic exposure/white-balance/autofocus retained to match operational app behavior")
            put("source_format", "CameraX ImageAnalysis YUV_420_888")
            put("reference_resolution", "640x480; CameraX closest-lower-then-higher fallback")
            put("model_sha256", modelHash)
            put("model_candidate", "dynamic_range")
            put("runtime", "TensorFlow Lite 2.17.0 CPU XNNPACK")
            put("class_names", JSONArray(SequencePlan.classLabels))
            put("config_sha256", config.sha256())
            put("collection_target_fps", stats.targetFps)
            put("duration_ms", stats.durationMs)
            put("camera_frames_seen", stats.cameraFramesSeen)
            put("sampled_frames", stats.sampledFrames)
            put("inference_frames", scoresCount)
            put("quality_passed_frames", stats.qualityPassedFrames)
            put("quality_rejected_frames", stats.qualityRejectedFrames)
            put("achieved_sample_fps", stats.achievedSampleFps)
            put("median_pipeline_ms", stats.medianPipelineMs)
            put("p95_pipeline_ms", stats.p95PipelineMs)
            put("target_5fps_capacity_ok", stats.p95PipelineMs <= 200.0)
            put("note", note)
            put("frames_csv_sha256", sha256(framesFile))
            put("stages_json_sha256", sha256(stagesFile))
            put("config_snapshot_sha256", sha256(configSnapshot))
            put("analysis_note", "Use quality-pass inference rows to replay candidate confidence thresholds 0.50..0.95 and temporal windows 1000/1500/2000 ms. Downsample the 5 FPS stream to evaluate 3 FPS.")
        }
        metadataFile.writeText(metadata.toString(2))

        appendManifest(metadata)
        val checklist = loadChecklist()
        val target = checklist.first { it.id == item.id }
        target.status = "SAVED"
        target.savedAtIso = now
        target.syncStatus = if (driveTreeUri == null) "LOCAL_ONLY" else "PENDING"
        writeChecklist(checklist)
        exportManifestCsv()

        return SavedSequence(
            item = target,
            relativeDir = rel,
            files = listOf(framesFile, stagesFile, metadataFile, configSnapshot)
        )
    }

    fun markSynced(itemId: String, synced: Boolean) {
        val items = loadChecklist()
        items.firstOrNull { it.id == itemId }?.syncStatus = if (synced) "SYNCED" else "PENDING"
        writeChecklist(items)
    }

    fun markAllSavedSynced() {
        val items = loadChecklist()
        items.filter { it.status == "SAVED" }.forEach { it.syncStatus = "SYNCED" }
        writeChecklist(items)
    }

    fun deleteSavedSequence(itemId: String): DeletedSequence {
        val items = loadChecklist()
        val item = items.firstOrNull { it.id == itemId } ?: error("Sequence tidak ditemukan")
        require(item.status == "SAVED") { "Sequence belum tersimpan" }
        val rel = relativeDir(item)
        val dir = File(root(), rel)
        if (dir.exists() && !dir.deleteRecursively()) error("Folder sequence tidak dapat dihapus")
        rewriteManifestExcluding(itemId)
        item.status = "PENDING"
        item.savedAtIso = null
        item.syncStatus = "NOT_SAVED"
        writeChecklist(items)
        exportManifestCsv()
        return DeletedSequence(item, rel)
    }

    fun relativeDir(item: SequenceItem): String = when (item.kind) {
        SequenceKind.NOMINAL -> "sequences/nominal/${item.primaryLabel}/${item.scenario}/${item.id}"
        SequenceKind.NONUANG -> "sequences/nonuang/${item.scenario.replace(' ', '_')}/${item.id}"
        SequenceKind.TRANSITION -> "sequences/transition/${item.id}"
    }

    fun dataFilesForSync(): List<File> {
        val index = indexFiles().map { it.canonicalFile }.toSet()
        return root().walkTopDown().filter { it.isFile && it.canonicalFile !in index }.toList()
    }

    fun indexFiles(): List<File> = listOf(planFile(), checklistFile(), checklistCsvFile(), manifestJsonlFile(), manifestCsvFile(), configFile())
        .filter { it.exists() }

    private fun writeExperimentPlan() {
        val items = SequencePlan.build()
        val obj = JSONObject().apply {
            put("schema_version", 1)
            put("purpose", "Forty temporal calibration sequences per Android target device for Subchapter 5.7 post-inference parameter analysis")
            put("per_device_total", 40)
            put("nominal_sequences", 28)
            put("nonmoney_sequences", 6)
            put("transition_sequences", 6)
            put("collection_fps", 5)
            put("candidate_replay_fps", JSONArray(listOf(3, 5)))
            put("candidate_confidence_thresholds", JSONArray((50..95 step 5).map { it / 100.0 }))
            put("candidate_temporal_windows_ms", JSONArray(listOf(1000, 1500, 2000)))
            put("minimum_results", 3)
            put("smoothing", "mean of complete eight-class score vectors")
            put("camera", "rear camera only; automatic camera behavior retained to match the operational app")
            put("controlled_lighting_lux", "350-450")
            put("baseline_distance_cm", 20)
            put("focus_condition", "sharp at baseline; perturbation only when the sequence cue requires movement/distance/orientation")
            put("sequence_duration_ms", 12000)
            put("items", JSONArray().apply {
                items.forEach { item ->
                    put(JSONObject().apply {
                        put("id", item.id)
                        put("kind", item.kind.name.lowercase())
                        put("scenario", item.scenario)
                        put("primary_label", item.primaryLabel ?: JSONObject.NULL)
                        put("secondary_label", item.secondaryLabel ?: JSONObject.NULL)
                        put("stages", JSONArray().apply {
                            item.stages.forEach { s ->
                                put(JSONObject().apply {
                                    put("id", s.id)
                                    put("title", s.title)
                                    put("cue", s.cue)
                                    put("duration_ms", s.durationMs)
                                    put("expected_label", s.expectedLabel ?: JSONObject.NULL)
                                    put("analysis_role", s.analysisRole)
                                })
                            }
                        })
                    })
                }
            })
        }
        planFile().writeText(obj.toString(2))
    }

    private fun writeFramesCsv(file: File, records: List<FrameRecord>) {
        val headers = mutableListOf(
            "frame_index", "elapsed_ms", "stage_id", "stage_title", "expected_label", "analysis_role",
            "image_timestamp_ns", "rotation_degrees", "roi_width", "roi_height",
            "luma_mean_original", "luma_mean_processed", "laplacian_variance", "clahe_applied",
            "quality_pass", "quality_code",
            "score_1000", "score_2000", "score_5000", "score_10000", "score_20000", "score_50000", "score_100000", "score_nonuang",
            "top_label", "top_score", "preprocess_ms", "inference_ms", "pipeline_ms"
        )
        val sb = StringBuilder().appendLine(headers.joinToString(","))
        for (r in records) {
            val scores = r.scores
            val values = listOf(
                r.frameIndex.toString(), r.elapsedMs.toString(), r.stageId, r.stageTitle, r.expectedLabel ?: "", r.analysisRole,
                r.imageTimestampNs.toString(), r.rotationDegrees.toString(), r.roiWidth.toString(), r.roiHeight.toString(),
                r.originalMeanY.toString(), r.processedMeanY.toString(), r.laplacianVariance.toString(), r.claheApplied.toString(),
                r.qualityPass.toString(), r.qualityCode ?: "",
                scores?.getOrNull(0)?.toString() ?: "", scores?.getOrNull(1)?.toString() ?: "", scores?.getOrNull(2)?.toString() ?: "",
                scores?.getOrNull(3)?.toString() ?: "", scores?.getOrNull(4)?.toString() ?: "", scores?.getOrNull(5)?.toString() ?: "",
                scores?.getOrNull(6)?.toString() ?: "", scores?.getOrNull(7)?.toString() ?: "",
                r.topLabel ?: "", r.topScore?.toString() ?: "", r.preprocessMs.toString(), r.inferenceMs.toString(), r.pipelineMs.toString()
            )
            sb.appendLine(values.joinToString(",") { csv(it) })
        }
        file.writeText(sb.toString())
    }

    private fun writeStagesJson(file: File, item: SequenceItem) {
        var cursor = 0L
        val arr = JSONArray()
        item.stages.forEach { stage ->
            arr.put(JSONObject().apply {
                put("stage_id", stage.id)
                put("title", stage.title)
                put("cue", stage.cue)
                put("start_ms", cursor)
                put("end_ms", cursor + stage.durationMs)
                put("expected_label", stage.expectedLabel ?: JSONObject.NULL)
                put("analysis_role", stage.analysisRole)
            })
            cursor += stage.durationMs
        }
        file.writeText(JSONObject().apply {
            put("sequence_id", item.id)
            put("total_duration_ms", item.totalDurationMs)
            put("stages", arr)
        }.toString(2))
    }

    private fun loadChecklist(): MutableList<SequenceItem> {
        val arr = JSONArray(checklistFile().readText())
        val planById = SequencePlan.build().associateBy { it.id }
        val result = mutableListOf<SequenceItem>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            val base = planById[o.getString("id")] ?: error("Checklist tidak cocok dengan experiment plan")
            result += base.copy(
                status = o.optString("status", "PENDING"),
                savedAtIso = o.optString("saved_at_utc").takeIf { it.isNotBlank() },
                syncStatus = o.optString("sync_status", "NOT_SAVED")
            )
        }
        return result
    }

    private fun writeChecklist(items: List<SequenceItem>) {
        val arr = JSONArray()
        items.forEach { item ->
            arr.put(JSONObject().apply {
                put("id", item.id)
                put("kind", item.kind.name)
                put("scenario", item.scenario)
                put("primary_label", item.primaryLabel ?: "")
                put("secondary_label", item.secondaryLabel ?: "")
                put("status", item.status)
                put("saved_at_utc", item.savedAtIso ?: "")
                put("sync_status", item.syncStatus)
            })
        }
        checklistFile().writeText(arr.toString(2))

        val sb = StringBuilder().appendLine("sequence_id,kind,scenario,primary_label,secondary_label,status,saved_at_utc,sync_status")
        items.forEach { item ->
            sb.appendLine(listOf(
                item.id, item.kind.name.lowercase(), item.scenario, item.primaryLabel ?: "", item.secondaryLabel ?: "",
                item.status, item.savedAtIso ?: "", item.syncStatus
            ).joinToString(",") { csv(it) })
        }
        checklistCsvFile().writeText(sb.toString())
    }

    private fun appendManifest(metadata: JSONObject) {
        manifestJsonlFile().appendText(metadata.toString() + "\n")
    }

    private fun rewriteManifestExcluding(sequenceId: String) {
        if (!manifestJsonlFile().exists()) return
        val kept = manifestJsonlFile().readLines().filter { line ->
            if (line.isBlank()) false else try { JSONObject(line).optString("sequence_id") != sequenceId } catch (_: Throwable) { true }
        }
        manifestJsonlFile().writeText(if (kept.isEmpty()) "" else kept.joinToString("\n", postfix = "\n"))
    }

    private fun exportManifestCsv() {
        val headers = listOf(
            "sequence_id", "kind", "scenario", "primary_label", "secondary_label", "captured_at_utc",
            "device_alias", "device_serial", "device_manufacturer", "device_model", "device_device",
            "android_release", "sdk_int", "device_abi",
            "model_sha256", "config_sha256", "duration_ms", "camera_frames_seen", "sampled_frames",
            "inference_frames", "quality_passed_frames", "quality_rejected_frames", "achieved_sample_fps",
            "median_pipeline_ms", "p95_pipeline_ms", "target_5fps_capacity_ok", "note"
        )
        val sb = StringBuilder().appendLine(headers.joinToString(","))
        val lines = manifestJsonlFile().takeIf { it.exists() }?.readLines()?.filter { it.isNotBlank() }.orEmpty()
        lines.forEach { line ->
            val o = JSONObject(line)
            sb.appendLine(headers.joinToString(",") { key ->
                val value = if (!o.has(key) || o.isNull(key)) "" else o.get(key).toString()
                csv(value)
            })
        }
        manifestCsvFile().writeText(sb.toString())
    }

    private fun csv(value: String): String = "\"${value.replace("\"", "\"\"")}\""

    private fun nowUtc(): String = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }.format(Date())

    companion object {
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buffer)
                    if (n <= 0) break
                    digest.update(buffer, 0, n)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
        }
    }
}

data class SavedSequence(
    val item: SequenceItem,
    val relativeDir: String,
    val files: List<File>
)

data class DeletedSequence(
    val item: SequenceItem,
    val relativeDir: String
)
