package com.ivarna.fluxlinux.core.root

import com.ivarna.fluxlinux.core.system.SafeFiles
import java.io.File
import java.nio.file.Files
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Execute the generated root-side hash gate; no su or Android paths are used. */
class NamespaceAssetGuardTest {
    private val tmp = Files.createTempDirectory("flux-namespace-guard").toFile()
    private val binary = File(tmp, "flux-mntns").apply { writeText("fixture ELF bytes") }
    private val guard = File(tmp, "flux_namespace.sh").apply { writeText("fixture guard bytes") }
    private val ran = File(tmp, "ran")

    @After
    fun tearDown() {
        RootShell.seedAssetShaForTest(ChrootPaths.NAMESPACE_ASSET, null)
        RootShell.seedAssetShaForTest(ChrootPaths.NAMESPACE_GUARD_ASSET, null)
        SafeFiles.deleteTree(tmp)
    }

    private fun seed() {
        RootShell.seedAssetShaForTest(ChrootPaths.NAMESPACE_ASSET, RootShell.sha256Hex(binary.readBytes()))
        RootShell.seedAssetShaForTest(ChrootPaths.NAMESPACE_GUARD_ASSET, RootShell.sha256Hex(guard.readBytes()))
    }

    private fun execute(): Int {
        val cmd = RootShell.namespaceExecGuard()
            .replace(ChrootPaths.NAMESPACE_HELPER, binary.absolutePath)
            .replace(ChrootPaths.NAMESPACE_GUARD, guard.absolutePath) + "touch '${ran.absolutePath}'"
        val process = ProcessBuilder("/bin/sh", "-c", cmd).redirectErrorStream(true).start()
        process.inputStream.readBytes()
        return process.waitFor()
    }

    @Test
    fun exactPairRuns() {
        seed()
        assertEquals(0, execute())
        assertTrue(ran.isFile)
    }

    @Test
    fun unknownNativeHashRefuses() {
        seed()
        RootShell.seedAssetShaForTest(ChrootPaths.NAMESPACE_ASSET, null)
        assertEquals(127, execute())
        assertFalse(ran.exists())
    }

    @Test
    fun changedBinaryRefuses() {
        seed()
        binary.appendText("changed")
        assertEquals(127, execute())
        assertFalse(ran.exists())
    }

    @Test
    fun changedGuardRefuses() {
        seed()
        guard.appendText("changed")
        assertEquals(127, execute())
        assertFalse(ran.exists())
    }

    @Test
    fun matchingSymlinkRefuses() {
        seed()
        val target = File(tmp, "target")
        assertTrue(binary.renameTo(target))
        Files.createSymbolicLink(binary.toPath(), target.toPath())
        assertEquals(127, execute())
        assertFalse(ran.exists())
    }
}
