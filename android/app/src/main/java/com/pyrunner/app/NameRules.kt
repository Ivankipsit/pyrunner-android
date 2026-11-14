package com.pyrunner.app

object NameRules {
    private val pattern = Regex("^[A-Za-z0-9][A-Za-z0-9 _.-]*\\.py$")

    fun normalize(raw: String): String {
        var name = raw.trim()
        if (name.isEmpty()) throw IllegalArgumentException("Name is empty")
        if (!name.endsWith(".py")) name += ".py"
        if (name.length > 80) throw IllegalArgumentException("Name is too long")
        if (name.contains("..") || name.contains("/") || name.contains("\\") || name.contains("\u0000")) {
            throw IllegalArgumentException("Name is not allowed")
        }
        if (!pattern.matches(name)) {
            throw IllegalArgumentException("Use letters, numbers, spaces, dot, dash, or underscore")
        }
        return name
    }
}
