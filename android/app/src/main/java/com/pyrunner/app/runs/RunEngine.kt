package com.pyrunner.app.runs

import android.app.ActivityManager
import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process
import android.os.RemoteException
import com.pyrunner.app.Jsons
import com.pyrunner.app.NameRules
import java.io.File
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class RunEngine(private val service: RunService) {
    private val store = RunStore(File(service.filesDir, "runs"))
    private val imageBaseline = java.util.concurrent.ConcurrentHashMap<String, Map<String, String>>()
    private val gate = Any()
    private val main = Handler(Looper.getMainLooper())
    private val threadCancels = HashMap<String, CancelFlag>()
    private val threadAlive = HashMap<String, Thread>()

    @Volatile var listener: ((String) -> Unit)? = null
    @Volatile var clientAttached: Boolean = false
    @Volatile var closed: Boolean = false

    private val slots = arrayOf(
        Slot(0, Slot0Service::class.java),
        Slot(1, Slot1Service::class.java),
        Slot(2, Slot2Service::class.java),
    )

    private val incoming = Messenger(Handler(Looper.getMainLooper()) { msg ->
        val data = Bundle(msg.data)
        onSlotMessage(msg.what, data)
        true
    })

    init {
        try {
            killLeftoverSlotProcesses()
        } catch (_: Exception) {
        }
        store.failInterrupted()
        Thread({
            while (!closed) {
                try {
                    Thread.sleep(30_000)
                } catch (_: InterruptedException) {
                    break
                }
                if (!closed) enforceTimeouts()
            }
        }, "pyrunner-timeout").apply { isDaemon = true }.start()
    }

    fun start(name: String, source: String, scriptId: String?): RunRecord {
        if (source.length > 2_000_000) throw IllegalArgumentException("Script is larger than 2 MB")
        val safe = NameRules.normalize(name)
        val created = mutate {
            val record = store.create(safe, scriptId)
            val work = store.workDir(record.id)
            File(work, "main.py").writeText(source)
            imageBaseline[record.id] = LiveFiles.snapshot(work)
            record
        }
        return store.get(created.id) ?: created
    }

    fun stop(id: String): RunRecord {
        mutate {
            val record = store.get(id) ?: throw IllegalArgumentException("Unknown run")
            when (record.status) {
                "queued" -> finishStopped(record)
                "running" -> requestStop(record)
            }
        }
        return store.get(id) ?: throw IllegalArgumentException("Unknown run")
    }

    fun kill(id: String): RunRecord {
        var pid = -1
        var killedIndex = -1
        var connection: ServiceConnection? = null
        mutate {
            val record = store.get(id) ?: throw IllegalArgumentException("Unknown run")
            if (record.status !in setOf("queued", "running", "stopping")) return@mutate
            if (record.status == "queued") {
                val updated = record.copy(status = "killed", finishedAt = System.currentTimeMillis())
                store.save(updated)
                publishStatus(updated)
                return@mutate
            }
            val slot = slots.firstOrNull { it.runId == id }
            if (mode() == "thread" || slot == null || slot.pid <= 0) {
                threadCancels[id]?.cancel()
                val updated = record.copy(
                    status = "stopping",
                    error = "Force kill is not available in thread mode; asked the script to stop",
                )
                store.save(updated)
                publishStatus(updated)
                notice("Force kill is not available while using the shared interpreter.")
                scheduleConfirm(id)
                return@mutate
            }
            pid = slot.pid
            killedIndex = slot.index
            connection = slot.connection
            slot.runId = null
            slot.pid = -1
            slot.messenger = null
            slot.connection = null
            slot.state = "dead"
            val updated = record.copy(status = "killed", finishedAt = System.currentTimeMillis())
            store.save(updated)
            publishStatus(updated)
        }
        val toUnbind = connection
        if (toUnbind != null) {
            try {
                service.unbindService(toUnbind)
            } catch (_: Exception) {
            }
        }
        if (pid > 0) Process.killProcess(pid)
        if (killedIndex >= 0) {
            mutate {
                val slot = slots[killedIndex]
                if (slot.state == "dead") slot.state = "unbound"
            }
        }
        return store.get(id) ?: throw IllegalArgumentException("Unknown run")
    }

    fun listRuns(): List<RunRecord> = store.list()

    fun readLog(id: String, maxChars: Int): LogSlice = store.readLog(id, maxChars)

    fun listArtifacts(id: String): List<LiveFiles.ImageFile> {
        store.get(id) ?: throw IllegalArgumentException("Unknown run")
        val work = store.workDir(id)
        val baseline = imageBaseline[id] ?: emptyMap()
        return LiveFiles.listNew(work, baseline)
    }

    fun readArtifact(id: String, name: String): ByteArray {
        store.get(id) ?: throw IllegalArgumentException("Unknown run")
        return LiveFiles.read(store.workDir(id), name)
    }

    fun activeCount(): Int = store.list().count {
        it.status == "running" || it.status == "stopping" || it.status == "queued"
    }

    fun startProbe() {
        Thread {
            val result = try {
                doProbe()
            } catch (error: Exception) {
                probeJson(false, mode(), error.message ?: "probe failed")
            }
            service.getSharedPreferences("pyrunner", Context.MODE_PRIVATE)
                .edit()
                .putString("last_probe", result)
                .apply()
            publish(result)
        }.start()
    }

    private fun doProbe(): String {
        val first = start("probe_a.py", SCRIPT_A, null)
        val second = start("probe_b.py", SCRIPT_B, null)
        val sawA = waitLog(first.id, "TOKEN_A1", 60)
        val sawB = waitLog(second.id, "TOKEN_B1", 60)
        kill(first.id)
        val sawB2 = waitLog(second.id, "TOKEN_B2", 20)
        val statusA = waitStatus(first.id, setOf("killed"), 15)
        try {
            kill(second.id)
        } catch (_: Exception) {
        }
        val ok = sawA && sawB && sawB2 && statusA == "killed"
        return probeJson(ok, mode(), "A1=$sawA B1=$sawB B2=$sawB2 Astatus=$statusA")
    }

    private fun onSlotMessage(what: Int, data: Bundle) {
        val binds = synchronized(gate) {
            handleLocked(what, data)
            pump()
        }
        binds.forEach { doBind(it) }
        refreshForeground()
    }

    private fun handleLocked(what: Int, data: Bundle) {
        when (what) {
            SlotMsg.PONG -> {
                val slot = slots.getOrNull(data.getInt("slot", -1)) ?: return
                slot.pid = data.getInt("pid", -1)
                if (slot.state == "binding" || slot.state == "unbound") slot.state = "ready"
            }
            SlotMsg.OUTPUT -> {
                val runId = data.getString("runId") ?: return
                emitChunk(runId, data.getString("stream") ?: "stdout", data.getString("text") ?: return)
            }
            SlotMsg.EXIT -> {
                val runId = data.getString("runId") ?: return
                finish(runId, data.getInt("exitCode", 1), data.getString("error"))
                val slot = slots.firstOrNull { it.runId == runId }
                if (slot != null) {
                    slot.state = "ready"
                    slot.runId = null
                }
            }
            SlotMsg.DIED -> {
                val slot = slots.getOrNull(data.getInt("slot", -1)) ?: return
                val runId = slot.runId
                slot.messenger = null
                slot.pid = -1
                slot.connection = null
                slot.runId = null
                if (slot.state != "dead") slot.state = "unbound"
                if (runId != null) markKilled(runId, "Runner process ended")
            }
            SlotMsg.FAIL, SlotMsg.BIND_TIMEOUT -> {
                val slot = slots.getOrNull(data.getInt("slot", -1)) ?: return
                if (slot.state != "binding") return
                try {
                    slot.connection?.let { service.unbindService(it) }
                } catch (_: Exception) {
                }
                slot.state = "unbound"
                slot.connection = null
                slot.messenger = null
                service.getSharedPreferences("pyrunner", Context.MODE_PRIVATE)
                    .edit()
                    .putString("runner_mode", "thread")
                    .apply()
                notice("Process runners did not start. Switching to the shared interpreter.")
            }
        }
    }

    private fun <T> mutate(block: () -> T): T {
        val binds: List<Slot>
        val value: T
        synchronized(gate) {
            value = block()
            binds = pump()
        }
        binds.forEach { doBind(it) }
        refreshForeground()
        return value
    }

    private fun pump(): List<Slot> {
        if (closed) return emptyList()
        val binds = mutableListOf<Slot>()
        val queued = store.list().filter { it.status == "queued" }.sortedBy { it.createdAt }
        for (record in queued) {
            if (mode() == "thread") {
                if (threadAlive.values.count { it.isAlive } >= 3) break
                startThread(record)
                continue
            }
            val ready = slots.firstOrNull { it.state == "ready" }
            if (ready != null) {
                dispatchToSlot(ready, record)
                continue
            }
            val unbound = slots.firstOrNull { it.state == "unbound" }
            if (unbound != null) {
                unbound.state = "binding"
                binds.add(unbound)
            }
            break
        }
        return binds
    }

    private fun dispatchToSlot(slot: Slot, record: RunRecord) {
        val work = store.workDir(record.id)
        val script = File(work, "main.py")
        val running = record.copy(status = "running", startedAt = System.currentTimeMillis())
        store.save(running)
        publishStatus(running)
        slot.state = "busy"
        slot.runId = record.id
        val message = Message.obtain(null, SlotMsg.RUN)
        message.replyTo = incoming
        message.data = Bundle().apply {
            putString("runId", record.id)
            putString("scriptPath", script.absolutePath)
            putString("workdir", work.absolutePath)
        }
        try {
            slot.messenger?.send(message)
        } catch (_: RemoteException) {
            slot.state = "unbound"
            slot.runId = null
            finish(record.id, 1, "Runner is not connected")
        }
    }

    private fun startThread(record: RunRecord) {
        val flag = CancelFlag()
        threadCancels[record.id] = flag
        val running = record.copy(status = "running", startedAt = System.currentTimeMillis())
        store.save(running)
        publishStatus(running)
        val work = store.workDir(record.id)
        val script = File(work, "main.py")
        val thread = Thread {
            var code = 1
            var error: String? = null
            try {
                val raw = PythonEntry.run(
                    context = service,
                    source = script.readText(),
                    filename = script.absolutePath,
                    workdir = work.absolutePath,
                    chdir = false,
                    onStdout = { emitChunk(record.id, "stdout", it) },
                    onStderr = { emitChunk(record.id, "stderr", it) },
                    cancel = flag,
                )
                val parsed = Jsons.json.parseToJsonElement(raw).jsonObject
                code = parsed["exitCode"]?.jsonPrimitive?.int ?: 1
                val errorElement = parsed["error"]
                error = if (errorElement == null || errorElement is JsonNull) {
                    null
                } else {
                    errorElement.jsonPrimitive.contentOrNull
                }
            } catch (thrown: Exception) {
                error = thrown.message
            }
            val binds = synchronized(gate) {
                finish(record.id, code, error)
                pump()
            }
            binds.forEach { doBind(it) }
            refreshForeground()
        }
        thread.name = "pyrunner-${record.id}"
        threadAlive[record.id] = thread
        thread.start()
    }

    private fun requestStop(record: RunRecord) {
        val updated = record.copy(status = "stopping", error = null)
        store.save(updated)
        publishStatus(updated)
        threadCancels[record.id]?.cancel()
        val slot = slots.firstOrNull { it.runId == record.id }
        if (slot?.messenger != null) {
            val message = Message.obtain(null, SlotMsg.STOP)
            message.data = Bundle().apply { putString("runId", record.id) }
            try {
                slot.messenger?.send(message)
            } catch (_: RemoteException) {
            }
        }
        scheduleConfirm(record.id)
    }

    private fun finishStopped(record: RunRecord) {
        val updated = record.copy(status = "stopped", exitCode = 130, finishedAt = System.currentTimeMillis())
        store.save(updated)
        publishStatus(updated)
    }

    private fun finish(id: String, code: Int, error: String?) {
        val record = store.get(id) ?: return
        if (record.status == "killed") return
        val status = when {
            record.status == "stopping" && code != 0 -> "stopped"
            code == 0 -> "finished"
            code == 130 -> "stopped"
            else -> "failed"
        }
        val updated = record.copy(
            status = status,
            exitCode = code,
            error = error,
            finishedAt = System.currentTimeMillis(),
        )
        store.save(updated)
        threadCancels.remove(id)
        threadAlive.remove(id)
        publishStatus(updated)
    }

    private fun markKilled(id: String, error: String) {
        val record = store.get(id) ?: return
        if (record.status !in setOf("running", "stopping", "queued")) return
        val updated = record.copy(status = "killed", finishedAt = System.currentTimeMillis(), error = error)
        store.save(updated)
        publishStatus(updated)
    }

    private fun scheduleConfirm(id: String) {
        Thread {
            Thread.sleep(1500)
            mutate {
                val record = store.get(id) ?: return@mutate
                if (record.status != "stopping") return@mutate
                val thread = threadAlive[id]
                val slot = slots.firstOrNull { it.runId == id }
                val alive = (thread != null && thread.isAlive) || (slot != null && slot.pid > 0)
                if (!alive) return@mutate
                val updated = record.copy(
                    status = "running",
                    error = "Script caught the stop request and kept running",
                )
                store.save(updated)
                publishStatus(updated)
            }
        }.start()
    }

    private fun doBind(slot: Slot) {
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                slot.messenger = Messenger(binder)
                val ping = Message.obtain(null, SlotMsg.PING)
                ping.replyTo = incoming
                try {
                    slot.messenger?.send(ping)
                } catch (_: RemoteException) {
                    onSlotMessage(SlotMsg.FAIL, Bundle().apply { putInt("slot", slot.index) })
                }
            }

            override fun onServiceDisconnected(name: ComponentName) {
                onSlotMessage(SlotMsg.DIED, Bundle().apply { putInt("slot", slot.index) })
            }
        }
        slot.connection = connection
        val bound = service.bindService(Intent(service, slot.clazz), connection, Context.BIND_AUTO_CREATE)
        if (!bound) {
            onSlotMessage(SlotMsg.FAIL, Bundle().apply { putInt("slot", slot.index) })
            return
        }
        main.postDelayed({
            onSlotMessage(SlotMsg.BIND_TIMEOUT, Bundle().apply { putInt("slot", slot.index) })
        }, 45_000)
    }

    private fun refreshForeground() {
        val count = activeCount()
        if (count > 0) service.ensureForeground(count) else service.demote()
    }

    private fun enforceTimeouts() {
        val now = System.currentTimeMillis()
        val limit = 12L * 3600L * 1000L
        val victims = store.list().filter {
            it.status == "running" && it.startedAt != null && now - it.startedAt > limit
        }.map { it.id }
        for (id in victims) {
            try {
                kill(id)
            } catch (_: Exception) {
            }
        }
    }

    private fun killLeftoverSlotProcesses() {
        val manager = service.getSystemService(Service.ACTIVITY_SERVICE) as ActivityManager
        val prefix = service.packageName + ":runner"
        for (info in manager.runningAppProcesses.orEmpty()) {
            if (info.processName.startsWith(prefix)) Process.killProcess(info.pid)
        }
    }

    private fun emitChunk(id: String, stream: String, text: String) {
        val seq = store.appendChunk(id, text)
        publish(buildJsonObject {
            put("event", "output")
            put("runId", id)
            put("stream", stream)
            put("seq", seq)
            put("text", text)
        }.toString())
    }

    private fun publishStatus(record: RunRecord) {
        publish(buildJsonObject {
            put("event", "status")
            put("run", Jsons.json.encodeToJsonElement(record))
        }.toString())
    }

    private fun notice(text: String) {
        publish(buildJsonObject {
            put("event", "notice")
            put("text", text)
        }.toString())
    }

    private fun publish(json: String) {
        try {
            listener?.invoke(json)
        } catch (_: Exception) {
        }
    }

    private fun mode(): String {
        return service.getSharedPreferences("pyrunner", Context.MODE_PRIVATE)
            .getString("runner_mode", "process") ?: "process"
    }

    private fun waitLog(id: String, token: String, seconds: Int): Boolean {
        val deadline = System.currentTimeMillis() + seconds * 1000L
        while (System.currentTimeMillis() < deadline) {
            if (store.readLog(id, 200_000).text.contains(token)) return true
            Thread.sleep(50)
        }
        return false
    }

    private fun waitStatus(id: String, wanted: Set<String>, seconds: Int): String {
        val deadline = System.currentTimeMillis() + seconds * 1000L
        var status = ""
        while (System.currentTimeMillis() < deadline) {
            status = store.get(id)?.status ?: ""
            if (status in wanted) return status
            Thread.sleep(50)
        }
        return status
    }

    private fun probeJson(ok: Boolean, mode: String, detail: String): String = buildJsonObject {
        put("event", "probe")
        put("ok", ok)
        put("mode", mode)
        put("detail", detail)
    }.toString()

    private class Slot(val index: Int, val clazz: Class<out Service>) {
        var state: String = "unbound"
        var messenger: Messenger? = null
        var pid: Int = -1
        var runId: String? = null
        var connection: ServiceConnection? = null
    }

    companion object {
        private val SCRIPT_A = """
            import time
            print("TOKEN_A1", flush=True)
            while True:
                try:
                    time.sleep(0.4)
                except KeyboardInterrupt:
                    pass
        """.trimIndent() + "\n"

        private val SCRIPT_B = """
            import time
            print("TOKEN_B1", flush=True)
            time.sleep(2.0)
            print("TOKEN_B2", flush=True)
        """.trimIndent() + "\n"
    }
}
