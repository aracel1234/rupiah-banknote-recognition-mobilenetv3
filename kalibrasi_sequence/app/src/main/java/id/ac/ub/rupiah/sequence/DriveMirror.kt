package id.ac.ub.rupiah.sequence

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.util.concurrent.ConcurrentHashMap

/**
 * Mirrors the local research dataset to a user-selected Storage Access Framework tree.
 *
 * Google Drive allows duplicate display names and its DocumentsProvider can expose newly
 * created children with a short delay. The original implementation repeatedly resolved a
 * directory from its display name and could therefore create a second folder/file while the
 * first one had not appeared in the provider listing yet. This implementation keeps the URI
 * returned by createDirectory/createFile in a cache and always overwrites that exact document.
 * It also refuses a provider-created automatic "(1)" rename instead of silently accepting a
 * duplicate research artifact.
 */
class DriveMirror(private val context: Context) {
    private val documentCache = ConcurrentHashMap<String, DocumentFile>()
    private val duplicateWarnings = linkedSetOf<String>()

    fun clearCache() {
        documentCache.clear()
    }

    fun syncAll(treeUri: Uri, localRoot: File): SyncResult =
        syncFiles(treeUri, localRoot, localRoot.walkTopDown().filter { it.isFile }.toList())

    /**
     * Deletes one sample directory from every matching legacy path under the selected SAF tree.
     *
     * The traversal deliberately follows all same-name directories because an older app version
     * could create duplicate Google Drive folders. Only the final sample directory is deleted;
     * parent experiment folders are preserved and may be reused by later captures.
     */
    @Synchronized
    fun deleteSample(
        treeUri: Uri,
        deviceName: String,
        relativeDir: String,
        requireExisting: Boolean
    ): DeleteResult {
        duplicateWarnings.clear()
        val tree = DocumentFile.fromTreeUri(context, treeUri)
            ?: return DeleteResult(false, 0, "Folder tujuan tidak dapat dibuka")
        if (!tree.canWrite()) return DeleteResult(false, 0, "Folder tujuan tidak memiliki izin tulis")

        val roots = findDeviceRoots(tree, deviceName)
        if (roots.isEmpty()) {
            return if (requireExisting) {
                DeleteResult(false, 0, "Folder perangkat '$deviceName' tidak ditemukan pada folder Drive yang dipilih")
            } else {
                DeleteResult(true, 0, "Sampel tidak ditemukan di Drive; tidak ada berkas jarak jauh yang perlu dihapus")
            }
        }

        val parts = relativeDir.split('/').filter { it.isNotBlank() }
        if (parts.isEmpty()) return DeleteResult(false, 0, "Path sampel kosong")

        var parents = roots
        for (segment in parts.dropLast(1)) {
            val next = mutableListOf<DocumentFile>()
            parents.forEach { parent ->
                val matches = safeListFiles(parent).filter { it.isDirectory && it.name == segment }
                if (matches.size > 1) duplicateWarnings += "folder '$segment' memiliki ${matches.size} salinan lama"
                next += matches
            }
            parents = next
            if (parents.isEmpty()) break
        }

        val sampleName = parts.last()
        val targets = parents.flatMap { parent ->
            safeListFiles(parent).filter { it.isDirectory && it.name == sampleName }
        }.distinctBy { it.uri.toString() }

        if (targets.isEmpty()) {
            return if (requireExisting) {
                DeleteResult(false, 0, "Sampel '$sampleName' tidak ditemukan di Drive. Sinkronkan/refresh Drive lalu coba lagi${warningSuffix()}")
            } else {
                DeleteResult(true, 0, "Sampel tidak ditemukan di Drive; tidak ada berkas jarak jauh yang perlu dihapus${warningSuffix()}")
            }
        }

        var deleted = 0
        targets.forEach { target ->
            val ok = try { target.delete() } catch (_: Throwable) { false }
            if (!ok) {
                return DeleteResult(false, deleted, "Gagal menghapus '${target.name}' dari Drive${warningSuffix()}")
            }
            deleted++
        }
        clearCache()
        return DeleteResult(true, deleted, "Sampel dihapus dari Drive${warningSuffix()}")
    }

    @Synchronized
    fun syncFiles(treeUri: Uri, localRoot: File, sources: List<File>): SyncResult {
        duplicateWarnings.clear()
        val tree = DocumentFile.fromTreeUri(context, treeUri)
            ?: return SyncResult(false, 0, "Folder tujuan tidak dapat dibuka")
        if (!tree.canWrite()) return SyncResult(false, 0, "Folder tujuan tidak memiliki izin tulis")

        val deviceRoot = resolveDeviceRoot(tree, localRoot.name)
            ?: return SyncResult(false, 0, "Gagal membuka/membuat folder dataset perangkat")

        var copied = 0
        try {
            sources.distinctBy { it.canonicalPath }
                .filter { it.exists() && it.isFile }
                .forEach { source ->
                    require(isInside(source, localRoot)) { "File di luar root dataset" }
                    val rel = source.relativeTo(localRoot).invariantSeparatorsPath
                    val parts = rel.split('/').filter { it.isNotBlank() }
                    require(parts.isNotEmpty()) { "Path relatif kosong" }

                    var current = deviceRoot
                    for (dirName in parts.dropLast(1)) {
                        current = getOrCreateDir(current, dirName)
                            ?: throw IllegalStateException("Gagal membuat folder Drive: $dirName")
                    }

                    val target = getOrCreateFile(current, mimeFor(source), parts.last())
                        ?: throw IllegalStateException("Gagal membuat file Drive: ${parts.last()}")
                    context.contentResolver.openOutputStream(target.uri, "wt").use { out ->
                        requireNotNull(out) { "Tidak dapat membuka output ${target.uri}" }
                        source.inputStream().use { it.copyTo(out) }
                    }
                    copied++
                }
        } catch (t: Throwable) {
            val warning = warningSuffix()
            return SyncResult(false, copied, "Sinkronisasi dihentikan: ${t.message ?: t.javaClass.simpleName}$warning")
        }

        val warning = warningSuffix()
        return SyncResult(true, copied, "Sinkronisasi selesai$warning")
    }

    /**
     * Accept three reasonable user choices without creating a nested duplicate:
     * 1) user selected the parent of RupiahSequenceCollector;
     * 2) user selected RupiahSequenceCollector itself;
     * 3) user selected the current device folder itself.
     */
    private fun resolveDeviceRoot(tree: DocumentFile, deviceName: String): DocumentFile? {
        if (tree.name == deviceName && tree.isDirectory) {
            cache(tree, "DIR:$deviceName")
            return tree
        }

        val projectRoot = if (tree.name == PROJECT_ROOT && tree.isDirectory) {
            tree
        } else {
            getOrCreateDir(tree, PROJECT_ROOT) ?: return null
        }

        if (projectRoot.name == deviceName) return projectRoot
        return getOrCreateDir(projectRoot, deviceName)
    }

    private fun findDeviceRoots(tree: DocumentFile, deviceName: String): List<DocumentFile> {
        if (tree.name == deviceName && tree.isDirectory) return listOf(tree)

        val projectRoots = if (tree.name == PROJECT_ROOT && tree.isDirectory) {
            listOf(tree)
        } else {
            safeListFiles(tree).filter { it.isDirectory && it.name == PROJECT_ROOT }
        }
        if (projectRoots.size > 1) duplicateWarnings += "folder '$PROJECT_ROOT' memiliki ${projectRoots.size} salinan lama"

        val deviceRoots = projectRoots.flatMap { project ->
            safeListFiles(project).filter { it.isDirectory && it.name == deviceName }
        }.distinctBy { it.uri.toString() }
        if (deviceRoots.size > 1) duplicateWarnings += "folder '$deviceName' memiliki ${deviceRoots.size} salinan lama"
        return deviceRoots
    }

    private fun safeListFiles(dir: DocumentFile): List<DocumentFile> = try {
        dir.listFiles().toList()
    } catch (_: Throwable) {
        emptyList()
    }

    private fun getOrCreateDir(parent: DocumentFile, name: String): DocumentFile? {
        val key = cacheKey(parent, "D", name)
        documentCache[key]?.let { cached ->
            if (cached.exists() && cached.isDirectory) return cached
            documentCache.remove(key)
        }

        val matches = parent.listFiles().filter { it.isDirectory && it.name == name }
        if (matches.isNotEmpty()) {
            val chosen = chooseDirectory(matches)
            if (matches.size > 1) duplicateWarnings += "folder '$name' memiliki ${matches.size} salinan lama"
            documentCache[key] = chosen
            return chosen
        }

        val created = parent.createDirectory(name) ?: return null
        if (created.name != name) {
            // Never accept a provider-side automatic rename such as "1000 (1)".
            try { created.delete() } catch (_: Throwable) {}
            throw IllegalStateException("Provider mencoba membuat folder duplikat '$name' sebagai '${created.name}'. Pilih folder Drive baru/kosong lalu sinkronkan ulang.")
        }
        documentCache[key] = created
        return created
    }

    private fun getOrCreateFile(parent: DocumentFile, mime: String, name: String): DocumentFile? {
        val key = cacheKey(parent, "F", name)
        documentCache[key]?.let { cached ->
            if (cached.exists() && cached.isFile && cached.name == name) return cached
            documentCache.remove(key)
        }

        val matches = parent.listFiles().filter { it.isFile && it.name == name }
        if (matches.isNotEmpty()) {
            val chosen = matches.maxByOrNull { it.lastModified() } ?: matches.first()
            if (matches.size > 1) duplicateWarnings += "file '$name' memiliki ${matches.size} salinan lama"
            documentCache[key] = chosen
            return chosen
        }

        val created = parent.createFile(mime, name) ?: return null
        if (created.name != name) {
            // Google Drive may return "manifest (1).csv" if a same-name file exists but its
            // listing is stale. Delete the accidental duplicate and stop rather than corrupting
            // the experiment directory structure.
            try { created.delete() } catch (_: Throwable) {}
            throw IllegalStateException("Provider mencoba membuat file duplikat '$name' sebagai '${created.name}'. Tunggu sinkronisasi Drive atau gunakan folder Drive baru/kosong.")
        }
        documentCache[key] = created
        return created
    }

    /**
     * When an old buggy app has already produced same-name directories, continue in the one
     * that currently contains the most children. No old directory is deleted automatically.
     */
    private fun chooseDirectory(matches: List<DocumentFile>): DocumentFile =
        matches.maxWithOrNull(
            compareBy<DocumentFile> { safeChildCount(it) }
                .thenBy { it.lastModified() }
        ) ?: matches.first()

    private fun safeChildCount(dir: DocumentFile): Int = try {
        dir.listFiles().size
    } catch (_: Throwable) {
        0
    }

    private fun cache(document: DocumentFile, label: String) {
        documentCache["${document.uri}|$label"] = document
    }

    private fun cacheKey(parent: DocumentFile, kind: String, name: String): String =
        "${parent.uri}|$kind|$name"

    private fun isInside(file: File, root: File): Boolean {
        val filePath = file.canonicalFile.toPath()
        val rootPath = root.canonicalFile.toPath()
        return filePath.startsWith(rootPath)
    }

    private fun warningSuffix(): String = if (duplicateWarnings.isEmpty()) {
        ""
    } else {
        ". Peringatan: ${duplicateWarnings.joinToString("; ")}. Salinan lama tidak dihapus otomatis."
    }

    private fun mimeFor(file: File): String = when (file.extension.lowercase()) {
        "png" -> "image/png"
        "json" -> "application/json"
        "jsonl" -> "application/x-ndjson"
        "csv" -> "text/csv"
        else -> "application/octet-stream"
    }

    companion object {
        private const val PROJECT_ROOT = "RupiahSequenceCollector"
    }
}

data class SyncResult(val success: Boolean, val copiedFiles: Int, val message: String)
data class DeleteResult(val success: Boolean, val deletedDirectories: Int, val message: String)
