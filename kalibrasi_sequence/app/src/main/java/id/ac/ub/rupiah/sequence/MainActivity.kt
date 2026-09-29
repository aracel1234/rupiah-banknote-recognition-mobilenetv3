package id.ac.ub.rupiah.sequence

import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.LayoutInflater
import android.view.View
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var repo: SequenceRepository
    private lateinit var driveMirror: DriveMirror
    private lateinit var configStore: SequenceConfigStore
    private var config: SequenceConfig = SequenceConfig.default()

    private lateinit var previewView: PreviewView
    private lateinit var deviceText: TextView
    private lateinit var aliasInput: EditText
    private lateinit var statusText: TextView
    private lateinit var stageOverlay: TextView
    private lateinit var progressText: TextView
    private lateinit var instructionText: TextView
    private lateinit var noteInput: EditText
    private lateinit var sequenceSpinner: Spinner
    private lateinit var filterSpinner: Spinner
    private lateinit var startButton: Button
    private lateinit var abortButton: Button
    private lateinit var syncButton: Button
    private lateinit var adapter: ChecklistAdapter

    private val mainHandler = Handler(Looper.getMainLooper())
    private val ioExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var camera: SequenceCamera? = null
    private var cameraReady = false
    private var modelHash = ""
    private var items = mutableListOf<SequenceItem>()
    private var selectedItem: SequenceItem? = null
    private var uiSequenceStartMs = 0L
    private var countdownActive = false
    private var stageTicker: Runnable? = null

    private val permissionLauncher = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else toast("Izin kamera diperlukan untuk pengumpulan sequence.")
    }

    private val treeLauncher = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            try {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
            } catch (_: SecurityException) {}
            repo.driveTreeUri = uri
            driveMirror.clearCache()
            refreshStatus()
            toast("Folder Google Drive dipilih. Data tetap disimpan lokal terlebih dahulu.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        repo = SequenceRepository(this)
        driveMirror = DriveMirror(this)
        configStore = SequenceConfigStore(this)
        config = configStore.load()

        bindViews()
        setupUi()
        loadChecklist()
        ensureCameraPermission()
    }

    private fun bindViews() {
        previewView = findViewById(R.id.previewView)
        deviceText = findViewById(R.id.deviceText)
        aliasInput = findViewById(R.id.deviceAliasInput)
        statusText = findViewById(R.id.statusText)
        stageOverlay = findViewById(R.id.stageOverlay)
        progressText = findViewById(R.id.progressText)
        instructionText = findViewById(R.id.instructionText)
        noteInput = findViewById(R.id.noteInput)
        sequenceSpinner = findViewById(R.id.sequenceSpinner)
        filterSpinner = findViewById(R.id.filterSpinner)
        startButton = findViewById(R.id.startButton)
        abortButton = findViewById(R.id.abortButton)
        syncButton = findViewById(R.id.syncButton)

        findViewById<Button>(R.id.saveAliasButton).setOnClickListener {
            aliasInput.setText(repo.deviceAlias)
            toast("Alias perangkat dikunci untuk Redmi 4X.")
        }
        findViewById<Button>(R.id.chooseDriveButton).setOnClickListener { treeLauncher.launch(repo.driveTreeUri) }
        syncButton.setOnClickListener { syncAll() }
        findViewById<Button>(R.id.configButton).setOnClickListener { showConfigDialog() }
        startButton.setOnClickListener { startSelectedSequence() }
        abortButton.setOnClickListener { abortCurrentSequence() }
    }

    private fun setupUi() {
        deviceText.text = "Perangkat penelitian: ${DeviceIdentity.DISPLAY_TEXT}"
        aliasInput.setText(repo.deviceAlias)
        aliasInput.isFocusable = false
        aliasInput.isCursorVisible = false
        aliasInput.isLongClickable = false

        adapter = ChecklistAdapter { item ->
            if (item.status == "SAVED") showSavedSequence(item) else selectItem(item)
        }
        findViewById<RecyclerView>(R.id.checklistRecycler).apply {
            layoutManager = LinearLayoutManager(this@MainActivity)
            adapter = this@MainActivity.adapter
        }

        val filters = listOf("Belum selesai", "Tersimpan", "Semua", "Nominal", "Nonuang", "Transisi")
        filterSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, filters)
        filterSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) = refreshChecklistFilter()
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        sequenceSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (position in items.indices && !isBusy()) {
                    selectedItem = items[position]
                    refreshInstruction()
                    refreshButtons()
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
        refreshStatus()
    }

    private fun ensureCameraPermission() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startCamera()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startCamera() {
        camera?.close()
        cameraReady = false
        stageOverlay.text = "Menyiapkan kamera dan model…"
        refreshButtons()
        camera = SequenceCamera(
            context = this,
            owner = this,
            previewView = previewView,
            onReady = { hash ->
                runOnUiThread {
                    modelHash = hash
                    cameraReady = true
                    stageOverlay.text = "Siap • model ${hash.take(12)}…"
                    refreshStatus()
                    refreshButtons()
                }
            },
            onFrameRecorded = { record ->
                runOnUiThread {
                    if (camera?.isRecording() == true) {
                        progressText.text = buildString {
                            append("Merekam ${selectedItem?.id ?: ""} • frame ${record.frameIndex}")
                            append(" • kualitas ")
                            append(if (record.qualityPass) "lolos" else (record.qualityCode ?: "ditolak"))
                            if (record.topLabel != null) append(" • top=${record.topLabel} ${"%.3f".format(record.topScore)}")
                        }
                    }
                }
            },
            onSequenceFinished = { records, stats ->
                runOnUiThread { onSequenceFinished(records, stats) }
            },
            onError = { t ->
                runOnUiThread {
                    cameraReady = false
                    stopStageTicker()
                    setBusy(false)
                    stageOverlay.text = "Kesalahan: ${t.message ?: t.javaClass.simpleName}"
                    toast("Kesalahan kamera/model: ${t.message ?: t.javaClass.simpleName}")
                }
            }
        ).also { it.start(config) }
    }

    private fun loadChecklist() {
        items = repo.allItems()
        val previousId = selectedItem?.id
        val labels = items.map { "${it.id} • ${it.displayName} • ${it.status}" }
        sequenceSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)

        val selectedIndex = previousId?.let { id -> items.indexOfFirst { it.id == id } }?.takeIf { it >= 0 }
            ?: items.indexOfFirst { it.status != "SAVED" }.takeIf { it >= 0 }
            ?: 0
        if (items.isNotEmpty()) {
            sequenceSpinner.setSelection(selectedIndex, false)
            selectedItem = items[selectedIndex]
        }
        refreshChecklistFilter()
        refreshInstruction()
        refreshProgress()
        refreshStatus()
        refreshButtons()
    }

    private fun refreshChecklistFilter() {
        if (!::adapter.isInitialized) return
        val filtered = when (filterSpinner.selectedItemPosition) {
            0 -> items.filter { it.status != "SAVED" }
            1 -> items.filter { it.status == "SAVED" }
            3 -> items.filter { it.kind == SequenceKind.NOMINAL }
            4 -> items.filter { it.kind == SequenceKind.NONUANG }
            5 -> items.filter { it.kind == SequenceKind.TRANSITION }
            else -> items
        }
        adapter.submit(filtered)
    }

    private fun refreshProgress() {
        val saved = items.count { it.status == "SAVED" }
        val synced = items.count { it.syncStatus == "SYNCED" }
        progressText.text = "Progress perangkat ${repo.deviceAlias}: $saved/40 tersimpan • $synced sinkron ke Drive"
    }

    private fun refreshStatus() {
        val drive = if (repo.driveTreeUri == null) "belum dipilih" else "aktif"
        val cfg = if (config.confirmed) "TERKONFIRMASI ${config.sha256().take(12)}…" else "BELUM DIKONFIRMASI"
        val model = if (modelHash.isBlank()) "memuat" else modelHash.take(12) + "…"
        statusText.text = "Drive: $drive • Config 5.7.2: $cfg • Model: $model • Collector: 5 FPS"
    }

    private fun refreshInstruction() {
        val item = selectedItem ?: return
        instructionText.text = buildString {
            appendLine("${item.id} • ${item.displayName}")
            appendLine("Kondisi kendali: kamera belakang • 350–450 lux • objek tajam • posisi awal sekitar 20 cm (kecuali cue DISTANCE).")
            appendLine("Durasi: ${item.totalDurationMs / 1000} detik + countdown 3 detik")
            appendLine("Ikuti cue otomatis berikut:")
            var cursor = 0L
            item.stages.forEach { stage ->
                append("${cursor / 1000.0}-${(cursor + stage.durationMs) / 1000.0}s: ${stage.title}. ${stage.cue}")
                appendLine()
                cursor += stage.durationMs
            }
        }
    }

    private fun refreshButtons() {
        val item = selectedItem
        val busy = isBusy()
        startButton.isEnabled = !busy && cameraReady && config.confirmed && item != null && item.status != "SAVED"
        abortButton.isEnabled = busy
        sequenceSpinner.isEnabled = !busy
        filterSpinner.isEnabled = !busy
    }

    private fun isBusy(): Boolean = countdownActive || camera?.isRecording() == true

    private fun setBusy(busy: Boolean) {
        if (!busy) countdownActive = false
        refreshButtons()
    }

    private fun selectItem(item: SequenceItem) {
        if (isBusy()) return
        val idx = items.indexOfFirst { it.id == item.id }
        if (idx >= 0) {
            selectedItem = items[idx]
            sequenceSpinner.setSelection(idx)
            refreshInstruction()
        }
    }

    private fun startSelectedSequence() {
        val item = selectedItem ?: return
        if (!cameraReady) return toast("Kamera/model belum siap.")
        if (!config.confirmed) return toast("Konfirmasi parameter final 5.7.2 terlebih dahulu.")
        if (item.status == "SAVED") return toast("Sequence ini sudah tersimpan.")

        try {
            repo.validateConfigForRecording(config)
        } catch (t: Throwable) {
            return toast(t.message ?: "Konfigurasi tidak valid")
        }

        countdownActive = true
        refreshButtons()
        countdown(3, item)
    }

    private fun countdown(value: Int, item: SequenceItem) {
        if (!countdownActive) return
        if (value <= 0) {
            countdownActive = false
            try {
                camera?.beginSequence(item)
                uiSequenceStartMs = SystemClock.elapsedRealtime()
                startStageTicker(item)
                refreshButtons()
            } catch (t: Throwable) {
                setBusy(false)
                toast(t.message ?: "Sequence tidak dapat dimulai")
            }
            return
        }
        stageOverlay.text = "Mulai ${item.id} dalam $value…"
        mainHandler.postDelayed({ countdown(value - 1, item) }, 1_000)
    }

    private fun startStageTicker(item: SequenceItem) {
        stopStageTicker()
        var lastStage = ""
        val ticker = object : Runnable {
            override fun run() {
                if (camera?.isRecording() != true) return
                val elapsed = SystemClock.elapsedRealtime() - uiSequenceStartMs
                val stage = item.stageAt(elapsed.coerceAtMost(item.totalDurationMs - 1))
                val remaining = (item.totalDurationMs - elapsed).coerceAtLeast(0)
                stageOverlay.text = "${stage.title} • sisa ${"%.1f".format(remaining / 1000.0)} dtk\n${stage.cue}"
                if (stage.id != lastStage) {
                    previewView.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS)
                    lastStage = stage.id
                }
                mainHandler.postDelayed(this, 100)
            }
        }
        stageTicker = ticker
        mainHandler.post(ticker)
    }

    private fun stopStageTicker() {
        stageTicker?.let { mainHandler.removeCallbacks(it) }
        stageTicker = null
    }

    private fun abortCurrentSequence() {
        if (countdownActive) {
            countdownActive = false
            mainHandler.removeCallbacksAndMessages(null)
            stageOverlay.text = "Countdown dibatalkan. Tidak ada data disimpan."
            refreshButtons()
            return
        }
        if (camera?.isRecording() == true) {
            camera?.abortSequence()
            stopStageTicker()
            stageOverlay.text = "Sequence dibatalkan. Tidak ada data disimpan."
            refreshButtons()
        }
    }

    private fun onSequenceFinished(records: List<FrameRecord>, stats: SequenceRunStats) {
        val item = selectedItem ?: return
        stopStageTicker()
        stageOverlay.text = "Menyimpan ${item.id}…"
        startButton.isEnabled = false
        abortButton.isEnabled = false
        val note = noteInput.text.toString().trim()

        ioExecutor.execute {
            try {
                val saved = repo.saveSequence(item, config, modelHash, records, stats, note)
                val tree = repo.driveTreeUri
                var message = "Tersimpan lokal"
                if (tree != null) {
                    try {
                        val samplePass = driveMirror.syncFiles(tree, repo.rootDirectory(), saved.files)
                        repo.markSynced(item.id, samplePass.success)
                        if (samplePass.success) {
                            val indexPass = driveMirror.syncFiles(tree, repo.rootDirectory(), repo.indexFiles())
                            message = if (indexPass.success) "Tersimpan lokal + Drive" else "Data sequence sinkron; index menunggu sinkron ulang"
                        } else {
                            message = "Tersimpan lokal; sinkronisasi tertunda"
                        }
                    } catch (_: Throwable) {
                        repo.markSynced(item.id, false)
                        message = "Tersimpan lokal; sinkronisasi tertunda"
                    }
                }
                runOnUiThread {
                    noteInput.setText("")
                    selectedItem = null
                    loadChecklist()
                    stageOverlay.text = "${item.id} selesai • ${stats.sampledFrames} frame • p95 ${"%.1f".format(stats.p95PipelineMs)} ms"
                    toast("${item.id}: $message")
                }
            } catch (t: Throwable) {
                runOnUiThread {
                    stageOverlay.text = "Gagal menyimpan: ${t.message}"
                    refreshButtons()
                    toast("Gagal menyimpan sequence: ${t.message}")
                }
            }
        }
    }

    private fun showConfigDialog() {
        if (isBusy()) return
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_sequence_config, null)
        val roiSpinner = view.findViewById<Spinner>(R.id.roiSpinner)
        val blurInput = view.findViewById<EditText>(R.id.blurMinInput)
        val lumaMinInput = view.findViewById<EditText>(R.id.lumaMinInput)
        val lumaMaxInput = view.findViewById<EditText>(R.id.lumaMaxInput)
        val claheCheck = view.findViewById<CheckBox>(R.id.claheCheck)
        val clipSpinner = view.findViewById<Spinner>(R.id.clipSpinner)
        val gridSpinner = view.findViewById<Spinner>(R.id.gridSpinner)
        val confirmCheck = view.findViewById<CheckBox>(R.id.confirmConfigCheck)

        val rois = listOf("0.70", "0.80", "0.90")
        roiSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, rois)
        roiSpinner.setSelection(rois.indexOf(String.format(java.util.Locale.US, "%.2f", config.roiFraction)).coerceAtLeast(0))
        blurInput.setText(config.blurMin.toString())
        lumaMinInput.setText(config.lumaMin.toString())
        lumaMaxInput.setText(config.lumaMax.toString())
        claheCheck.isChecked = config.claheEnabled
        val clips = listOf("1.5", "2.0", "2.5")
        clipSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, clips)
        clipSpinner.setSelection(clips.indexOf(config.claheClipLimit.toString()).coerceAtLeast(0))
        val grids = listOf("4", "8")
        gridSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, grids)
        gridSpinner.setSelection(grids.indexOf(config.claheGrid.toString()).coerceAtLeast(0))
        confirmCheck.isChecked = config.confirmed

        val locked = repo.hasSavedSequences()
        listOf<View>(roiSpinner, blurInput, lumaMinInput, lumaMaxInput, claheCheck, clipSpinner, gridSpinner, confirmCheck)
            .forEach { it.isEnabled = !locked }

        val dialog = AlertDialog.Builder(this)
            .setTitle(if (locked) "Konfigurasi terkunci" else "Konfigurasi final 5.7.2")
            .setView(view)
            .setNegativeButton("Batal", null)
            .setPositiveButton(if (locked) "Tutup" else "Simpan", null)
            .create()

        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (locked) {
                    dialog.dismiss()
                    return@setOnClickListener
                }
                try {
                    val newConfig = SequenceConfig(
                        roiFraction = rois[roiSpinner.selectedItemPosition].toFloat(),
                        roiAspect = SequenceConfig.DEFAULT_ROI_ASPECT,
                        blurMin = blurInput.text.toString().toDouble(),
                        lumaMin = lumaMinInput.text.toString().toDouble(),
                        lumaMax = lumaMaxInput.text.toString().toDouble(),
                        claheEnabled = claheCheck.isChecked,
                        claheClipLimit = clips[clipSpinner.selectedItemPosition].toDouble(),
                        claheGrid = grids[gridSpinner.selectedItemPosition].toInt(),
                        confirmed = confirmCheck.isChecked
                    )
                    configStore.save(newConfig)
                    config = newConfig
                    if (newConfig.confirmed) repo.persistConfirmedConfig(newConfig)
                    dialog.dismiss()
                    refreshStatus()
                    cameraReady = false
                    startCamera()
                } catch (t: Throwable) {
                    toast("Konfigurasi tidak valid: ${t.message}")
                }
            }
        }
        dialog.show()
    }

    private fun showSavedSequence(item: SequenceItem) {
        val message = buildString {
            appendLine(item.displayName)
            appendLine("ID: ${item.id}")
            appendLine("Status: ${item.status} / ${item.syncStatus}")
            appendLine("Disimpan: ${item.savedAtIso ?: "-"}")
            appendLine()
            append("Hapus hanya jika sequence salah dan memang perlu direkam ulang.")
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle("Sequence tersimpan")
            .setMessage(message)
            .setNegativeButton("Tutup", null)
            .setPositiveButton("Hapus & rekam ulang", null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                confirmDelete(item, dialog)
            }
        }
        dialog.show()
    }

    private fun confirmDelete(item: SequenceItem, parent: AlertDialog) {
        val tree = repo.driveTreeUri
        if ((item.syncStatus == "SYNCED" || item.syncStatus == "PENDING") && tree == null) {
            toast("Pilih kembali folder Drive yang sama sebelum menghapus sequence yang pernah disinkronkan.")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Hapus ${item.id}?")
            .setMessage("Folder sequence lokal dan salinan Drive (jika ada) akan dihapus, lalu slot kembali PENDING. Sequence lain tidak disentuh.")
            .setNegativeButton("Batal", null)
            .setPositiveButton("Hapus") { _, _ ->
                ioExecutor.execute {
                    try {
                        if (tree != null) {
                            val remote = driveMirror.deleteSample(
                                treeUri = tree,
                                deviceName = repo.rootDirectory().name,
                                relativeDir = repo.relativeDir(item),
                                requireExisting = item.syncStatus == "SYNCED"
                            )
                            if (!remote.success) error(remote.message)
                        }
                        repo.deleteSavedSequence(item.id)
                        if (tree != null) driveMirror.syncFiles(tree, repo.rootDirectory(), repo.indexFiles())
                        runOnUiThread {
                            parent.dismiss()
                            loadChecklist()
                            selectItem(items.first { it.id == item.id })
                            toast("${item.id} kembali PENDING")
                        }
                    } catch (t: Throwable) {
                        runOnUiThread { toast("Penghapusan dibatalkan: ${t.message}") }
                    }
                }
            }
            .show()
    }

    private fun syncAll() {
        val tree = repo.driveTreeUri ?: return toast("Pilih folder Google Drive terlebih dahulu.")
        syncButton.isEnabled = false
        ioExecutor.execute {
            try {
                val data = driveMirror.syncFiles(tree, repo.rootDirectory(), repo.dataFilesForSync())
                var result = data
                if (data.success) {
                    repo.markAllSavedSynced()
                    val index = driveMirror.syncFiles(tree, repo.rootDirectory(), repo.indexFiles())
                    result = SyncResult(index.success, data.copiedFiles + index.copiedFiles, index.message)
                }
                runOnUiThread {
                    syncButton.isEnabled = true
                    loadChecklist()
                    toast(result.message)
                }
            } catch (t: Throwable) {
                runOnUiThread {
                    syncButton.isEnabled = true
                    toast("Sinkronisasi gagal: ${t.message}")
                }
            }
        }
    }

    override fun onStop() {
        if (isBusy()) abortCurrentSequence()
        super.onStop()
    }

    override fun onDestroy() {
        stopStageTicker()
        camera?.close()
        ioExecutor.shutdown()
        super.onDestroy()
    }

    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}
