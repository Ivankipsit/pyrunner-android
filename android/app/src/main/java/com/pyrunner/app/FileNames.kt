package com.pyrunner.app

import java.io.File

object FileNames {
    private val namePattern = Regex("^[A-Za-z0-9][A-Za-z0-9 _.-]{0,80}$")
    private val keyPattern = Regex("^[A-Za-z0-9_-]{1,40}$")
    const val MAX_BYTES = 8_000_000
    val skip = setOf("main.py", "sitecustomize.py")

    fun filename(raw: String): String {
        val name = raw.trim().replace('\\', '/').substringAfterLast('/').trim()
        if (name.isEmpty() || name == "." || name == ".." || name.startsWith(".") || name.contains("..") || name.contains('\u0000')) {
            throw IllegalArgumentException("File name is not allowed")
        }
        if (!namePattern.matches(name)) {
            throw IllegalArgumentException("Use letters, numbers, spaces, dot, dash, or underscore")
        }
        return name
    }

    fun inboxKey(scriptId: String?): String {
        val key = scriptId?.trim().orEmpty().ifEmpty { "scratch" }
        if (!keyPattern.matches(key)) throw IllegalArgumentException("Script id is not allowed")
        return key
    }

    fun listFiles(folder: File): List<String> {
        if (!folder.isDirectory) return emptyList()
        return folder.listFiles()
            ?.filter { it.isFile && it.name !in skip }
            ?.map { it.name }
            ?.sorted()
            ?: emptyList()
    }

    fun copyInto(work: File, folder: File?) {
        if (folder == null || !folder.isDirectory) return
        work.mkdirs()
        for (name in listFiles(folder)) {
            val source = File(folder, name)
            source.copyTo(File(work, filename(name)), overwrite = true)
        }
    }
}
