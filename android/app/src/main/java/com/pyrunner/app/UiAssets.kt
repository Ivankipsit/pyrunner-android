package com.pyrunner.app

/**
 * Maps a UI URL onto a file inside the APK assets directory.
 * The https://appassets host is only a name WebView uses for relative links.
 * The bytes are read from the APK. Nothing is fetched from the network.
 */
object UiAssets {
    fun assetPath(url: String?): String? {
        if (!WebPolicy.isAllowedAppAsset(url)) return null
        val relative = url!!.substringBefore('#').removePrefix(WebPolicy.UI_BASE)
        return "web/$relative"
    }

    fun mimeType(path: String): String = when {
        path.endsWith(".html") -> "text/html"
        path.endsWith(".css") -> "text/css"
        path.endsWith(".js") -> "text/javascript"
        path.endsWith(".svg") -> "image/svg+xml"
        path.endsWith(".png") -> "image/png"
        path.endsWith(".jpg") || path.endsWith(".jpeg") -> "image/jpeg"
        path.endsWith(".webp") -> "image/webp"
        path.endsWith(".json") -> "application/json"
        path.endsWith(".txt") || path.endsWith(".md") -> "text/plain"
        else -> "application/octet-stream"
    }

    fun charset(path: String): String? {
        val mime = mimeType(path)
        return if (mime.startsWith("text/") || mime == "application/json" || mime == "image/svg+xml") {
            "utf-8"
        } else {
            null
        }
    }
}
