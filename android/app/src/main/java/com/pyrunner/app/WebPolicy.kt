package com.pyrunner.app

/**
 * The UI is served only from the APK, through WebViewAssetLoader's
 * appassets host. That host is intercepted inside the app and is not a
 * network request. Anything else is refused.
 */
object WebPolicy {
    const val APP_ASSET_HOST = "appassets.androidplatform.net"
    const val UI_BASE = "https://$APP_ASSET_HOST/assets/web/"

    fun isAllowedAppAsset(url: String?): Boolean {
        if (url.isNullOrEmpty()) return false
        val withoutFragment = url.substringBefore('#')
        if (withoutFragment.any { it == '?' || it == '\\' || it.isWhitespace() }) return false
        if (!withoutFragment.startsWith(UI_BASE)) return false
        val path = withoutFragment.removePrefix(UI_BASE)
        if (path.isEmpty() || path.startsWith("/")) return false
        val lower = path.lowercase()
        if (lower.contains("..") || lower.contains("%") || lower.contains("//")) return false
        return true
    }
}
