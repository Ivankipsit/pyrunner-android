package com.pyrunner.app.runs

import android.app.Application
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process
import android.os.RemoteException
import android.util.Log
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

object SlotMsg {
    const val RUN = 1
    const val STOP = 2
    const val KILL = 3
    const val OUTPUT = 4
    const val EXIT = 5
    const val PING = 6
    const val PONG = 7
    const val DIED = 8
    const val FAIL = 9
    const val BIND_TIMEOUT = 10
}

object ProcessNames {
    fun current(): String {
        if (Build.VERSION.SDK_INT >= 28) return Application.getProcessName()
        return try {
            File("/proc/self/cmdline").readBytes().toString(Charsets.ISO_8859_1).substringBefore('\u0000')
        } catch (_: Exception) {
            ""
        }
    }

    fun slotIndex(): Int {
        val name = current()
        val marker = ":runner"
        val at = name.lastIndexOf(marker)
        if (at < 0) return -1
        return name.substring(at + marker.length).toIntOrNull() ?: -1
    }
}

open class RunnerSlotService : Service() {
    private var client: Messenger? = null
    private var running = false
    private var cancel: CancelFlag? = null
    private val json = Json { ignoreUnknownKeys = true }
    private val messenger = Messenger(Handler(Looper.getMainLooper()) { msg ->
        when (msg.what) {
            SlotMsg.PING -> {
                client = msg.replyTo
                send(msg.replyTo, SlotMsg.PONG, Bundle().apply {
                    putInt("pid", Process.myPid())
                    putInt("slot", ProcessNames.slotIndex())
                })
            }
            SlotMsg.RUN -> startRun(msg)
            SlotMsg.STOP -> cancel?.cancel()
            SlotMsg.KILL -> {
                cancel?.cancel()
                Process.killProcess(Process.myPid())
            }
        }
        true
    })

    override fun onBind(intent: Intent): IBinder = messenger.binder

    override fun onUnbind(intent: Intent): Boolean {
        cancel?.cancel()
        stopSelf()
        return false
    }

    private fun startRun(msg: Message) {
        val data = msg.data
        val runId = data.getString("runId")
        val scriptPath = data.getString("scriptPath")
        val workdir = data.getString("workdir")
        val replyTo = msg.replyTo ?: client
        if (runId == null || scriptPath == null || workdir == null || replyTo == null) return
        if (running) {
            send(replyTo, SlotMsg.EXIT, Bundle().apply {
                putString("runId", runId)
                putInt("exitCode", 1)
                putString("error", "Runner is busy")
            })
            return
        }
        running = true
        val flag = CancelFlag()
        cancel = flag
        Thread {
            var code = 1
            var error: String? = null
            try {
                val source = File(scriptPath).readText()
                val raw = PythonEntry.run(
                    context = this,
                    source = source,
                    filename = scriptPath,
                    workdir = workdir,
                    chdir = true,
                    onStdout = { text ->
                        send(replyTo, SlotMsg.OUTPUT, Bundle().apply {
                            putString("runId", runId)
                            putString("stream", "stdout")
                            putString("text", text)
                        })
                    },
                    onStderr = { text ->
                        send(replyTo, SlotMsg.OUTPUT, Bundle().apply {
                            putString("runId", runId)
                            putString("stream", "stderr")
                            putString("text", text)
                        })
                    },
                    cancel = flag,
                )
                val parsed = json.parseToJsonElement(raw).jsonObject
                code = parsed["exitCode"]?.jsonPrimitive?.int ?: 1
                val errorEl = parsed["error"]
                error = if (errorEl == null || errorEl is JsonNull) null else errorEl.jsonPrimitive.contentOrNull
            } catch (errorThrown: Exception) {
                Log.e("PyRunner", "slot run failed", errorThrown)
                error = errorThrown.message ?: "Runner failed"
            } finally {
                running = false
                cancel = null
                send(replyTo, SlotMsg.EXIT, Bundle().apply {
                    putString("runId", runId)
                    putInt("exitCode", code)
                    if (error != null) putString("error", error)
                })
            }
        }.start()
    }

    private fun send(target: Messenger?, what: Int, data: Bundle) {
        if (target == null) return
        val message = Message.obtain(null, what)
        message.data = data
        try {
            target.send(message)
        } catch (_: RemoteException) {
        }
    }
}

class Slot0Service : RunnerSlotService()
class Slot1Service : RunnerSlotService()
class Slot2Service : RunnerSlotService()
