package com.pyrunner.app

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

object CapabilityReport {
    private const val TIMEOUT_SEC = 12 * 3600

    fun build(context: Context): JsonObject {
        val prefs = context.getSharedPreferences("pyrunner", Context.MODE_PRIVATE)
        val thread = prefs.getString("runner_mode", "process") == "thread"
        return buildJsonObject {
            put("appVersion", "0.1.0")
            put("platform", "android")
            put("python", "3.13")
            put("distribution", "sideload")
            put("concurrencyMode", if (thread) "thread" else "process")
            put("runnerSlots", 3)
            put("features", buildJsonObject {
                put("liveOutput", true)
                put("concurrentRuns", true)
                put("hardKill", !thread)
                put("cooperativeStop", true)
                put("scriptLibrary", true)
                put("filePicker", true)
                put("foregroundService", true)
                put("pipRuntime", false)
                put("multiprocessing", false)
                put("playwright", false)
                put("selenium", false)
                put("localAgent", false)
                put("webviewRender", false)
            })
            put("packages", packages(context))
            put("limits", buildJsonObject { put("runTimeoutSec", TIMEOUT_SEC) })
            put("notes", buildJsonArray {
                add("Playwright and Selenium are not part of the Android build.")
                add("Packages with native code are fixed when the APK is built.")
                add("Force-kill uses separate app processes. If those processes do not start, PyRunner switches to one shared interpreter.")
                if (thread) {
                    add("This device is using the shared interpreter. A stuck native call cannot be force-killed.")
                }
            })
            val last = prefs.getString("last_probe", null)
            if (!last.isNullOrBlank()) {
                try {
                    put("lastProbe", Json.parseToJsonElement(last))
                } catch (_: Exception) {
                }
            }
        }
    }

    private fun packages(context: Context): JsonArray = buildJsonArray {
        val text = try {
            context.assets.open("packages.txt").bufferedReader().use { it.readText() }
        } catch (_: Exception) {
            ""
        }
        for (line in text.lineSequence()) {
            val trimmed = line.trim()
            if (trimmed.isEmpty() || trimmed.startsWith("#") || "==" !in trimmed) continue
            val name = trimmed.substringBefore("==")
            val version = trimmed.substringAfter("==")
            add(buildJsonObject {
                put("name", name)
                put("version", version)
                put("installed", true)
                put("source", "build")
            })
        }
    }
}
