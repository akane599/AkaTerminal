package com.ivarna.fluxlinux.core.terminal

import com.termux.terminal.PtySizeCoalescer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The vendored :terminal-emulator's pty resize coalescing (keyboard / window-drag bursts). */
class PtySizeCoalescerTest {

    private class FakeScheduler : PtySizeCoalescer.Scheduler {
        val pending = mutableListOf<Runnable>()
        override fun postDelayed(task: Runnable, delayMs: Long) {
            pending += task
        }

        override fun cancel(task: Runnable) {
            pending.remove(task)
        }

        fun runAll() {
            val tasks = pending.toList()
            pending.clear()
            tasks.forEach { it.run() }
        }
    }

    private val scheduler = FakeScheduler()
    private val applied = mutableListOf<Pair<Int, Int>>()
    private val coalescer = PtySizeCoalescer(scheduler, { c, r -> applied += c to r }, 120, 80, 40)

    @Test
    fun burstOfSizes_appliesOnlyTheLast() {
        for (rows in 39 downTo 22) coalescer.request(80, rows)
        assertEquals(1, scheduler.pending.size)
        assertTrue(applied.isEmpty())
        scheduler.runAll()
        assertEquals(listOf(80 to 22), applied)
    }

    @Test
    fun burstThatEndsWhereItStarted_appliesNothing() {
        coalescer.request(80, 30)
        coalescer.request(80, 22)
        coalescer.request(80, 40)
        scheduler.runAll()
        assertTrue(applied.isEmpty())
    }

    @Test
    fun separateChanges_eachApply() {
        coalescer.request(80, 22)
        scheduler.runAll()
        coalescer.request(100, 22)
        scheduler.runAll()
        assertEquals(listOf(80 to 22, 100 to 22), applied)
    }

    @Test
    fun cancel_dropsThePendingSize() {
        coalescer.request(80, 22)
        coalescer.cancel()
        scheduler.runAll()
        assertTrue(applied.isEmpty())
    }
}
