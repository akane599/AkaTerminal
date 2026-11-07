package com.ivarna.fluxlinux.core.terminal

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TerminalFontTest {

    @Test
    fun equalWidths_areMonospace() {
        assertTrue(TerminalFont.isMonospace(floatArrayOf(28.8f, 28.8f, 28.8f, 28.8f)))
    }

    @Test
    fun subPixelRounding_isStillMonospace() {
        assertTrue(TerminalFont.isMonospace(floatArrayOf(28.8f, 28.9f, 28.75f)))
    }

    @Test
    fun proportionalWidths_areRejected() {
        // Roboto-like: i is far narrower than W.
        assertFalse(TerminalFont.isMonospace(floatArrayOf(11f, 41f, 38f, 12f)))
    }

    @Test
    fun emptyOrZeroWidths_areRejected() {
        assertFalse(TerminalFont.isMonospace(floatArrayOf()))
        assertFalse(TerminalFont.isMonospace(floatArrayOf(0f, 0f)))
    }
}
