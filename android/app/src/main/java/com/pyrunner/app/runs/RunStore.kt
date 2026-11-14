package com.pyrunner.app.runs

import java.io.File
import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class RunRecord(
    val id: String,
    val name: String,
    val scriptId: String? = null,
    val status: String,
    val exitCode: Int? = null,
    val error: String? = null,
    val createdAt: Long,
    val startedAt: Long? = null,
    val finishedAt: Long? = null,
)

data class LogSlice(val text: String, val nextSeq: Int, val truncated: Boolean)

class RunStore(private val root: File) {
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true; encodeDefaults = true }
    private val seqs = HashMap<String, Int>()
    private val locks = HashMap<String, Any>()

    init {
        root.mkdirs()
    }

    fun create(name: String, scriptId: String?): RunRecord {
        val id = UUID.randomUUID().toString().replace("-", "").take(12)
        val record = RunRecord(
            id = id,
            name = name,
            scriptId = scriptId,
            status = "queued",
            createdAt = System.currentTimeMillis(),
        )
        workDir(id)
        logFile(id).writeText("")
        save(record)
        return record
    }

    fun get(id: String): RunRecord? {
        val file = metaFile(id)
        if (!file.exists()) return null
        return json.decodeFromString(RunRecord.serializer(), file.readText())
    }

    fun save(record: RunRecord) {
        val file = metaFile(record.id)
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, "meta.json.tmp")
        tmp.writeText(json.encodeToString(RunRecord.serializer(), record))
        if (file.exists()) file.delete()
        if (!tmp.renameTo(file)) {
            tmp.copyTo(file, overwrite = true)
            tmp.delete()
        }
    }

    fun list(): List<RunRecord> {
        val dirs = root.listFiles() ?: return emptyList()
        return dirs.mapNotNull { dir ->
            if (!dir.isDirectory) null else get(dir.name)
        }.sortedByDescending { it.createdAt }
    }

    fun workDir(id: String): File {
        val dir = File(dirFor(id), "work")
        dir.mkdirs()
        return dir
    }

    fun appendChunk(id: String, text: String): Int = synchronized(lock(id)) {
        val seq = seqs.getOrDefault(id, 0)
        logFile(id).appendText(text)
        seqs[id] = seq + 1
        seq
    }

    fun readLog(id: String, maxChars: Int): LogSlice = synchronized(lock(id)) {
        val file = logFile(id)
        val all = if (file.exists()) file.readText() else ""
        val truncated = all.length > maxChars
        val text = if (truncated) all.takeLast(maxChars) else all
        LogSlice(text, seqs.getOrDefault(id, 0), truncated)
    }

    fun failInterrupted() {
        for (record in list()) {
            if (record.status == "running" || record.status == "stopping" || record.status == "queued") {
                save(
                    record.copy(
                        status = "failed",
                        finishedAt = System.currentTimeMillis(),
                        error = "The app process restarted before this script finished.",
                    ),
                )
            }
        }
    }

    private fun lock(id: String): Any = synchronized(locks) { locks.getOrPut(id) { Any() } }

    private fun dirFor(id: String): File {
        require(id.matches(Regex("[a-f0-9]{8,32}"))) { "Unknown run" }
        return File(root, id).apply { mkdirs() }
    }

    private fun metaFile(id: String) = File(dirFor(id), "meta.json")

    private fun logFile(id: String) = File(dirFor(id), "log.txt")
}
