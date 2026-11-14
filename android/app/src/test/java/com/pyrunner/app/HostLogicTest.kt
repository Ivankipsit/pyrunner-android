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
        assertTrue(WebPolicy.isAllowedAppAsset(WebPolicy.UI_BASE + "index.html"))
        assertTrue(WebPolicy.isAllowedAppAsset(WebPolicy.UI_BASE + "js/app.js"))
        assertFalse(WebPolicy.isAllowedAppAsset("https://example.com/"))
        assertFalse(WebPolicy.isAllowedAppAsset("http://appassets.androidplatform.net/assets/web/index.html"))
        assertFalse(WebPolicy.isAllowedAppAsset("file:///android_asset/web/index.html"))
        assertFalse(WebPolicy.isAllowedAppAsset(WebPolicy.UI_BASE + "../secret"))
        assertFalse(WebPolicy.isAllowedAppAsset(WebPolicy.UI_BASE + "%2e%2e/secret"))
        assertFalse(WebPolicy.isAllowedAppAsset(null))
    }

    @Test
    fun bundledUiBootsFromAppAssets() {
        val ui = listOf(File("../../ui"), File("../ui"), File("ui"))
            .first { File(it, "index.html").isFile }
        val html = File(ui, "index.html").readText()
        val refs = Regex("""(?:src|href)\s*=\s*"([^"]+)"""")
            .findAll(html)
            .map { it.groupValues[1] }
            .toList()
        assertEquals(listOf("css/app.css", "vendor/codemirror-bundle.js", "js/app.js"), refs)
        for (ref in refs) {
            assertFalse(ref.contains("://"))
            val file = File(ui, ref)
            assertTrue("$ref is missing", file.isFile && file.length() > 0)
            assertTrue(WebPolicy.isAllowedAppAsset(WebPolicy.UI_BASE + ref))
        }
        val script = File(ui, "js/app.js").readText()
        assertTrue(script.contains("async function boot("))
        assertTrue(script.contains("boot();"))
        assertTrue(script.contains("PyRunnerAndroid"))
        assertEquals("web/index.html", UiAssets.assetPath(WebPolicy.UI_BASE + "index.html"))
        assertEquals("web/css/app.css", UiAssets.assetPath(WebPolicy.UI_BASE + "css/app.css"))
        assertEquals("web/js/app.js", UiAssets.assetPath(WebPolicy.UI_BASE + "js/app.js"))
        assertEquals("web/vendor/codemirror-bundle.js", UiAssets.assetPath(WebPolicy.UI_BASE + "vendor/codemirror-bundle.js"))
        assertEquals("text/html", UiAssets.mimeType("web/index.html"))
        assertEquals("text/css", UiAssets.mimeType("web/css/app.css"))
        assertEquals("text/javascript", UiAssets.mimeType("web/js/app.js"))
        assertEquals(null, UiAssets.assetPath("https://example.com/index.html"))
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
