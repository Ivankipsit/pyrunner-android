package com.pyrunner.app

object WebPolicy {
    fun isAllowedAsset(url: String?): Boolean {
        if (url.isNullOrEmpty()) return false
        val lower = url.lowercase()
        if (!lower.startsWith("file:///android_asset/web/")) return false
        if (lower.contains("..") || lower.contains("%2e%2e")) return false
        return true
    }
}
