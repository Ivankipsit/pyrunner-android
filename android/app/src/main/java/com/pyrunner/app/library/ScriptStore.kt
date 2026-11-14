package com.pyrunner.app.library

import com.pyrunner.app.NameRules
import java.io.File
import java.util.UUID
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class ScriptMeta(
    val id: String,
    val name: String,
    val createdAt: Long,
    val updatedAt: Long,
)

@Serializable
data class ScriptIndex(val scripts: List<ScriptMeta> = emptyList())

data class ScriptRecord(val meta: ScriptMeta, val source: String)

class ScriptStore(private val root: File) {
    private val dir = File(root, "scripts").apply { mkdirs() }
    private val indexFile = File(root, "index.json")
    private val lock = Any()
    private val json = Json { ignoreUnknownKeys = true; prettyPrint = true }

    fun list(): List<ScriptMeta> = synchronized(lock) {
        read().sortedByDescending { it.updatedAt }
    }

    fun get(id: String): ScriptRecord = synchronized(lock) {
        val meta = find(read(), id)
        ScriptRecord(meta, fileFor(id).readText())
    }

    fun save(id: String?, name: String, source: String): ScriptMeta = synchronized(lock) {
        if (source.length > 2_000_000) throw IllegalArgumentException("Script is larger than 2 MB")
        val safe = NameRules.normalize(name)
        val items = read()
        val now = System.currentTimeMillis()
        val meta = if (id == null) {
            ensureUnique(items, safe, null)
            ScriptMeta(newId(), safe, now, now)
        } else {
            val current = find(items, id)
            ensureUnique(items, safe, id)
            current.copy(name = safe, updatedAt = now)
        }
        fileFor(meta.id).writeText(source)
        val updated = if (id == null) items + meta else items.map { if (it.id == meta.id) meta else it }
        write(updated)
        meta
    }

    fun rename(id: String, name: String): ScriptMeta = synchronized(lock) {
        val safe = NameRules.normalize(name)
        val items = read()
        val current = find(items, id)
        ensureUnique(items, safe, id)
        val meta = current.copy(name = safe, updatedAt = System.currentTimeMillis())
        write(items.map { if (it.id == id) meta else it })
        meta
    }

    fun delete(id: String) = synchronized(lock) {
        val items = read()
        find(items, id)
        fileFor(id).delete()
        write(items.filter { it.id != id })
    }

    private fun ensureUnique(items: List<ScriptMeta>, name: String, id: String?) {
        if (items.any { it.name == name && it.id != id }) {
            throw IllegalArgumentException("A script named $name is already in the library")
        }
    }

    private fun find(items: List<ScriptMeta>, id: String): ScriptMeta {
        return items.firstOrNull { it.id == id } ?: throw IllegalArgumentException("Unknown script")
    }

    private fun fileFor(id: String): File {
        require(id.matches(Regex("[a-f0-9]{8,32}"))) { "Unknown script" }
        return File(dir, "$id.py")
    }

    private fun read(): List<ScriptMeta> {
        if (!indexFile.exists()) return emptyList()
        return json.decodeFromString(ScriptIndex.serializer(), indexFile.readText()).scripts
    }

    private fun write(items: List<ScriptMeta>) {
        val tmp = File(indexFile.parentFile, indexFile.name + ".tmp")
        tmp.writeText(json.encodeToString(ScriptIndex.serializer(), ScriptIndex(items)))
        if (indexFile.exists()) indexFile.delete()
        if (!tmp.renameTo(indexFile)) {
            tmp.copyTo(indexFile, overwrite = true)
            tmp.delete()
        }
    }

    private fun newId(): String = UUID.randomUUID().toString().replace("-", "").take(12)
}
