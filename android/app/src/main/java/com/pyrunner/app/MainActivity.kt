package com.pyrunner.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.provider.OpenableColumns
import android.provider.Settings
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.util.Base64
import android.webkit.WebViewClient
import java.io.IOException
import android.view.ViewGroup
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.pyrunner.app.library.ScriptStore
import com.pyrunner.app.runs.RunEngine
import com.pyrunner.app.runs.RunRecord
import com.pyrunner.app.runs.RunService
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    private lateinit var library: ScriptStore
    private var webView: WebView? = null
    private var runService: RunService? = null
    private val bound = CountDownLatch(1)
    private var openFuture: CompletableFuture<Uri?>? = null

    private val openDoc = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        openFuture?.complete(uri)
        openFuture = null
    }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, service: IBinder) {
            val boundService = (service as RunService.LocalBinder).service()
            runService = boundService
            boundService.engine.clientAttached = true
            boundService.engine.listener = { json -> deliver(json) }
            bound.countDown()
        }

        override fun onServiceDisconnected(name: ComponentName) {
            runService = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        library = ScriptStore(java.io.File(filesDir, "library"))
        seedExamples()
        requestNotifications()
        val view = WebView(this)
        webView = view
        configure(view)
        val frame = FrameLayout(this)
        frame.addView(
            view,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        setContentView(frame)
        paintSystemBars()
        applySystemInsets(frame)
        bindService(Intent(this, RunService::class.java), connection, BIND_AUTO_CREATE)
        view.loadUrl(WebPolicy.UI_BASE + "index.html")
    }

    override fun onDestroy() {
        runService?.engine?.listener = null
        runService?.engine?.clientAttached = false
        try {
            unbindService(connection)
        } catch (_: Exception) {
        }
        webView?.apply {
            removeJavascriptInterface("PyRunnerAndroid")
            destroy()
        }
        webView = null
        super.onDestroy()
    }

    fun handle(raw: String): String {
        val request = try {
            Jsons.json.parseToJsonElement(raw).jsonObject
        } catch (_: Exception) {
            return Jsons.err("Bad request")
        }
        val method = Jsons.text(request, "method")?.takeIf { it.isNotBlank() } ?: return Jsons.err("Missing method")
        val params = request["params"] as? JsonObject ?: JsonObject(emptyMap())
        return try {
            Jsons.ok(dispatch(method, params))
        } catch (error: Exception) {
            Jsons.err(error.message ?: "error")
        }
    }

    private fun dispatch(method: String, params: JsonObject) = when (method) {
        "capabilities" -> CapabilityReport.build(this)
        "listScripts" -> buildJsonArray {
            library.list().forEach { add(Jsons.json.encodeToJsonElement(it)) }
        }
        "getScript" -> {
            val record = library.get(Jsons.text(params, "id") ?: throw IllegalArgumentException("id is required"))
            buildJsonObject {
                put("id", record.meta.id)
                put("name", record.meta.name)
                put("source", record.source)
                put("createdAt", record.meta.createdAt)
                put("updatedAt", record.meta.updatedAt)
            }
        }
        "saveScript" -> Jsons.json.encodeToJsonElement(
            library.save(
                Jsons.text(params, "id")?.takeIf { it.isNotBlank() },
                Jsons.text(params, "name") ?: "",
                Jsons.text(params, "source") ?: throw IllegalArgumentException("source is required"),
            ),
        )
        "renameScript" -> Jsons.json.encodeToJsonElement(
            library.rename(
                Jsons.text(params, "id") ?: throw IllegalArgumentException("id is required"),
                Jsons.text(params, "name") ?: "",
            ),
        )
        "deleteScript" -> {
            library.delete(Jsons.text(params, "id") ?: throw IllegalArgumentException("id is required"))
            buildJsonObject { put("deleted", true) }
        }
        "openFile" -> openFile()
        "run" -> runJson(engine().start(
            Jsons.text(params, "name") ?: "untitled.py",
            Jsons.text(params, "source") ?: throw IllegalArgumentException("source is required"),
            Jsons.text(params, "scriptId"),
        ))
        "stop" -> runJson(engine().stop(Jsons.text(params, "runId") ?: throw IllegalArgumentException("runId is required")))
        "kill" -> runJson(engine().kill(Jsons.text(params, "runId") ?: throw IllegalArgumentException("runId is required")))
        "listRuns" -> buildJsonArray { engine().listRuns().forEach { add(Jsons.json.encodeToJsonElement(it)) } }
        "readLog" -> {
            val slice = engine().readLog(
                Jsons.text(params, "runId") ?: throw IllegalArgumentException("runId is required"),
                Jsons.int(params, "maxChars", 200_000),
            )
            buildJsonObject {
                put("text", slice.text)
                put("nextSeq", slice.nextSeq)
                put("truncated", slice.truncated)
            }
        }
        "listArtifacts" -> {
            val id = Jsons.text(params, "runId") ?: throw IllegalArgumentException("runId is required")
            buildJsonArray {
                for (item in engine().listArtifacts(id)) {
                    add(buildJsonObject {
                        put("name", item.name)
                        put("kind", "image")
                        put("bytes", item.bytes)
                    })
                }
            }
        }
        "readArtifact" -> {
            val id = Jsons.text(params, "runId") ?: throw IllegalArgumentException("runId is required")
            val name = Jsons.text(params, "name") ?: throw IllegalArgumentException("name is required")
            val bytes = engine().readArtifact(id, name)
            buildJsonObject {
                put("name", name)
                put("mime", com.pyrunner.app.runs.LiveFiles.mime(name))
                put("base64", Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
        }
        "concurrencyProbe" -> {
            engine().startProbe()
            buildJsonObject { put("started", true) }
        }
        "setRunnerMode" -> {
            val mode = Jsons.text(params, "mode") ?: throw IllegalArgumentException("mode is required")
            if (mode != "process" && mode != "thread") throw IllegalArgumentException("mode must be process or thread")
            getSharedPreferences("pyrunner", MODE_PRIVATE).edit().putString("runner_mode", mode).apply()
            buildJsonObject { put("mode", mode) }
        }
        "agentStatus" -> buildJsonObject {
            put("ollama", false)
            put("selected", "builtin")
            put("installed", buildJsonArray { })
            put("pulling", "")
        }
        "agentSelect" -> {
            val id = Jsons.text(params, "id") ?: "builtin"
            if (id != "builtin") {
                throw IllegalArgumentException("This phone uses the built-in helper. Download a model on Windows.")
            }
            buildJsonObject { put("selected", "builtin") }
        }
        "agentPull", "agentDelete" -> throw IllegalArgumentException(
            "This phone uses the built-in helper. Download or delete a model on Windows. That stays on 127.0.0.1.",
        )
        "agentAsk" -> throw IllegalArgumentException("Ask the built-in helper on this phone. It does not call a model.")
        "agentBridgeInfo" -> buildJsonObject { put("enabled", false) }
        "agentSync" -> buildJsonObject { put("enabled", false) }
        "agentResolve" -> throw IllegalArgumentException("A local coding agent connects on Windows only.")
        "requestBatteryExemption" -> {
            val intent = Intent(
                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:$packageName"),
            )
            runOnUiThread { startActivity(intent) }
            buildJsonObject { put("started", true) }
        }
        "pipInstall" -> throw IllegalArgumentException("pip install at runtime is only available on the desktop build")
        else -> throw IllegalArgumentException("Unknown method: $method")
    }

    private fun openFile(): JsonObject {
        val uri = pickPythonFile() ?: return buildJsonObject { put("cancelled", true) }
        val name = displayName(uri)
        val bytes = contentResolver.openInputStream(uri)?.use { readCapped(it, 2_000_000) }
            ?: throw IllegalArgumentException("Could not read the file")
        return buildJsonObject {
            put("cancelled", false)
            put("name", name)
            put("content", String(bytes, Charsets.UTF_8))
        }
    }

    private fun pickPythonFile(): Uri? {
        val future = CompletableFuture<Uri?>()
        runOnUiThread {
            openFuture?.complete(null)
            openFuture = future
            openDoc.launch(arrayOf("text/x-python", "text/plain", "application/octet-stream"))
        }
        return try {
            future.get(5, TimeUnit.MINUTES)
        } catch (_: Exception) {
            null
        }
    }

    private fun displayName(uri: Uri): String {
        var name = "opened.py"
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val value = cursor.getString(0)
                if (!value.isNullOrBlank()) name = value
            }
        }
        return name
    }

    private fun engine(): RunEngine {
        if (runService == null) {
            bound.await(8, TimeUnit.SECONDS)
        }
        return runService?.engine ?: throw IllegalStateException("Run service did not start")
    }

    private fun deliver(json: String) {
        val view = webView ?: return
        val argument = JSONObject.quote(json)
        view.post {
            view.evaluateJavascript("window.pyrunner&&window.pyrunner.receive(JSON.parse($argument))", null)
        }
    }

    private fun seedExamples() {
        if (library.list().isNotEmpty()) return
        val names = assets.list("examples") ?: return
        for (name in names.sorted()) {
            if (!name.endsWith(".py")) continue
            val source = assets.open("examples/$name").bufferedReader().use { it.readText() }
            try {
                library.save(null, name, source)
            } catch (_: Exception) {
            }
        }
    }

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT < 33) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return
        }
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
    }

    private fun applySystemInsets(frame: FrameLayout) {
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes = window.attributes.apply {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        if (Build.VERSION.SDK_INT >= 29) {
            window.isStatusBarContrastEnforced = false
            window.isNavigationBarContrastEnforced = false
        }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        ViewCompat.setOnApplyWindowInsetsListener(frame) { target, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or
                    WindowInsetsCompat.Type.displayCutout() or
                    WindowInsetsCompat.Type.ime(),
            )
            target.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            WindowInsetsCompat.CONSUMED
        }
        ViewCompat.requestApplyInsets(frame)
    }

    private fun paintSystemBars() {
        @Suppress("DEPRECATION")
        window.statusBarColor = Color.parseColor("#14160F")
        @Suppress("DEPRECATION")
        window.navigationBarColor = Color.parseColor("#14160F")
        if (Build.VERSION.SDK_INT >= 30) {
            val controller = window.decorView.windowInsetsController ?: return
            controller.setSystemBarsAppearance(
                0,
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                    WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            )
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configure(view: WebView) {
        if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true)
        val settings = view.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = false
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        settings.setGeolocationEnabled(false)
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true
        if (Build.VERSION.SDK_INT >= 26) settings.safeBrowsingEnabled = false
        settings.blockNetworkLoads = true
        CookieManager.getInstance().setAcceptCookie(false)
        view.addJavascriptInterface(JsBridge(this), "PyRunnerAndroid")
        view.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                return !WebPolicy.isAllowedAppAsset(request.url?.toString())
            }

            @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
            override fun shouldInterceptRequest(view: WebView, url: String): WebResourceResponse {
                return serve(url)
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
                return serve(request.url?.toString())
            }
        }
    }
}

class JsBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun invoke(request: String): String = try {
        activity.handle(request)
    } catch (error: Exception) {
        Jsons.err(error.message ?: "error")
    }
}

private fun MainActivity.serve(url: String?): WebResourceResponse {
    val path = UiAssets.assetPath(url) ?: return blocked()
    return try {
        WebResourceResponse(UiAssets.mimeType(path), UiAssets.charset(path), assets.open(path))
    } catch (_: IOException) {
        blocked()
    }
}

private fun blocked(): WebResourceResponse {
    return WebResourceResponse(
        "text/plain",
        "utf-8",
        200,
        "OK",
        emptyMap<String, String>(),
        ByteArrayInputStream(ByteArray(0)),
    )
}

private fun readCapped(input: InputStream, cap: Int): ByteArray {
    val out = ByteArrayOutputStream()
    val buffer = ByteArray(8192)
    var total = 0
    while (total <= cap) {
        val read = input.read(buffer)
        if (read < 0) break
        total += read
        if (total > cap) throw IllegalArgumentException("File is larger than 2 MB")
        out.write(buffer, 0, read)
    }
    return out.toByteArray()
}

private fun runJson(record: RunRecord) = Jsons.json.encodeToJsonElement(record)
