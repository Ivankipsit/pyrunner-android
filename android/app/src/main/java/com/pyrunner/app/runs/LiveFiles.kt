package com.pyrunner.app.runs

import java.io.File
import java.nio.file.Files

/**
 * Images written while a script runs. Paths stay inside the run folder.
 */
object LiveFiles {
    private val suffixes = setOf("png", "jpg", "jpeg", "gif", "webp")
    const val MAX_BYTES = 1_500_000
    private const val MAX_FILES = 24

    data class ImageFile(val name: String, val bytes: Long)

    fun snapshot(root: File): Map<String, String> {
        return walk(root).associate { it.name to signature(File(root, it.name)) }
    }

    fun listNew(root: File, baseline: Map<String, String>): List<ImageFile> {
        return walk(root)
            .filter { baseline[it.name] != signature(File(root, it.name)) }
            .take(MAX_FILES)
    }

    fun read(root: File, name: String): ByteArray {
        val file = safe(root, name)
        if (file.length() > MAX_BYTES) throw IllegalArgumentException("Image is larger than 1.5 MB")
        return file.readBytes()
    }

    fun mime(name: String): String = when (extension(name)) {
        "png" -> "image/png"
        "jpg", "jpeg" -> "image/jpeg"
        "gif" -> "image/gif"
        "webp" -> "image/webp"
        else -> "application/octet-stream"
    }

    private fun walk(root: File): List<ImageFile> {
        if (!root.isDirectory) return emptyList()
        val found = ArrayList<ImageFile>()
        walkInto(root, root, found)
        found.sortBy { it.name }
        return found
    }

    private fun walkInto(root: File, dir: File, found: MutableList<ImageFile>) {
        val children = dir.listFiles() ?: return
        for (child in children) {
            if (child.name == "__pycache__" || child.name.startsWith(".")) continue
            if (child.isDirectory) {
                walkInto(root, child, found)
            } else if (suffixes.contains(extension(child.name)) && !child.isSymlink()) {
                val name = child.relativeTo(root).invariantSeparatorsPath
                found.add(ImageFile(name, child.length()))
            }
        }
    }

    private fun safe(root: File, name: String): File {
        if (name.isBlank() || name.startsWith("/") || name.startsWith("\\") || name.contains('\\') || name.contains(':')) {
            throw IllegalArgumentException("bad path")
        }
        val parts = name.split('/')
        if (parts.any { it.isEmpty() || it == "." || it == ".." }) throw IllegalArgumentException("bad path")
        if (!suffixes.contains(extension(name))) throw IllegalArgumentException("not an image")
        var file = root
        for (part in parts) file = File(file, part)
        val rootPath = root.canonicalFile
        val candidate = file.canonicalFile
        val rootPrefix = rootPath.path.trimEnd('/') + "/"
        if (candidate.path != rootPath.path && !candidate.path.startsWith(rootPrefix)) {
            throw IllegalArgumentException("bad path")
        }
        if (!candidate.isFile) throw IllegalArgumentException("not an image")
        return candidate
    }

    private fun signature(file: File): String = "${file.length()}:${file.lastModified()}"

    private fun extension(name: String): String {
        val dot = name.lastIndexOf('.')
        if (dot < 0 || dot == name.length - 1) return ""
        return name.substring(dot + 1).lowercase()
    }

    private fun File.isSymlink(): Boolean = Files.isSymbolicLink(toPath())
}
