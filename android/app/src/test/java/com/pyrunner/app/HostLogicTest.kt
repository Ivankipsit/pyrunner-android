package com.pyrunner.app

import com.pyrunner.app.library.ScriptStore
import com.pyrunner.app.runs.RunStore
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class HostLogicTest {
    @Test
    fun namesMatchTheDesktopRules() {
        assertEquals("hello.py", NameRules.normalize("hello"))
        assertEquals("My script.py", NameRules.normalize("My script.py"))
        assertThrows(IllegalArgumentException::class.java) { NameRules.normalize("../x.py") }
        assertThrows(IllegalArgumentException::class.java) { NameRules.normalize("a/b.py") }
        assertThrows(IllegalArgumentException::class.java) { NameRules.normalize("") }
    }

    @Test
    fun webViewOnlyLoadsBundledPages() {
        assertTrue(WebPolicy.isAllowedAsset("file:///android_asset/web/index.html"))
        assertTrue(WebPolicy.isAllowedAsset("file:///android_asset/web/js/app.js"))
        assertFalse(WebPolicy.isAllowedAsset("https://example.com/"))
        assertFalse(WebPolicy.isAllowedAsset("file:///android_asset/web/../secret"))
        assertFalse(WebPolicy.isAllowedAsset("file:///android_asset/web/%2e%2e/secret"))
        assertFalse(WebPolicy.isAllowedAsset(null))
    }

    @Test
    fun libraryRoundTrip() {
        val root = File.createTempFile("lib", "").apply { delete(); mkdirs() }
        val store = ScriptStore(root)
        val created = store.save(null, "one", "print(1)\n")
        assertEquals("one.py", created.name)
        val updated = store.save(created.id, "one.py", "print(2)\n")
        assertEquals(created.id, updated.id)
        assertEquals("print(2)\n", store.get(created.id).source)
        assertEquals("two.py", store.rename(created.id, "two").name)
        val other = store.save(null, "three", "x")
        assertThrows(IllegalArgumentException::class.java) { store.rename(other.id, "two.py") }
        store.delete(created.id)
        assertEquals(listOf(other.id), store.list().map { it.id })
    }

    @Test
    fun runLogAndInterruptedCleanup() {
        val root = File.createTempFile("runs", "").apply { delete(); mkdirs() }
        val store = RunStore(root)
        val run = store.create("job.py", null)
        assertEquals("queued", run.status)
        assertEquals(0, store.appendChunk(run.id, "hello"))
        assertEquals(1, store.appendChunk(run.id, "\n"))
        val slice = store.readLog(run.id, 100)
        assertEquals("hello\n", slice.text)
        assertEquals(2, slice.nextSeq)
        assertFalse(slice.truncated)
        store.save(run.copy(status = "running", startedAt = 1L))
        store.failInterrupted()
        assertEquals("failed", store.get(run.id)?.status)
        val tail = store.readLog(run.id, 4)
        assertTrue(tail.truncated)
        assertEquals("llo\n", tail.text)
    }
}
