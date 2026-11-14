package com.pyrunner.app

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

object Jsons {
    val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    fun ok(result: JsonElement): String = buildJsonObject {
        put("ok", true)
        put("result", result)
    }.toString()

    fun err(message: String): String = buildJsonObject {
        put("ok", false)
        put("error", message)
    }.toString()

    fun text(params: JsonObject, key: String): String? {
        val element = params[key] ?: return null
        if (element is JsonNull || element !is JsonPrimitive || !element.isString) return null
        return element.content
    }

    fun int(params: JsonObject, key: String, default: Int): Int {
        val element = params[key] ?: return default
        if (element !is JsonPrimitive) return default
        return element.content.toIntOrNull() ?: default
    }
}
