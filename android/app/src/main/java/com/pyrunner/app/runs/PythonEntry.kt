package com.pyrunner.app.runs

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.io.RandomAccessFile

class TextSink(private val onText: (String) -> Unit) {
    fun write(text: String?) {
        if (text.isNullOrEmpty()) return
        var index = 0
        while (index < text.length) {
            val end = minOf(index + 8192, text.length)
            onText(text.substring(index, end))
            index = end
        }
    }
}

class CancelFlag {
    @Volatile private var cancelled = false

    fun cancel() {
        cancelled = true
    }

    fun isCancelled(): Boolean = cancelled
}

object PythonBoot {
    fun ensureStarted(context: Context) {
        if (Python.isStarted()) return
        val lockFile = File(context.filesDir, "python-boot.lock")
        RandomAccessFile(lockFile, "rw").use { file ->
            file.channel.lock().use {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(context.applicationContext))
                }
            }
        }
    }
}

object PythonEntry {
    fun run(
        context: Context,
        source: String,
        filename: String,
        workdir: String,
        chdir: Boolean,
        onStdout: (String) -> Unit,
        onStderr: (String) -> Unit,
        cancel: CancelFlag,
    ): String {
        PythonBoot.ensureStarted(context)
        val module = Python.getInstance().getModule("pyrunner_rt.execute")
        val result = module.callAttr(
            "execute_source_json",
            source,
            filename,
            workdir,
            TextSink(onStdout),
            TextSink(onStderr),
            cancel,
            chdir,
        )
        return result.toString()
    }
}
