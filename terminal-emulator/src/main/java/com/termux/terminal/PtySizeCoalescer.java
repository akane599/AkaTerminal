package com.termux.terminal;

/**
 * Coalesces pty window-size changes (local fix, not upstream).
 * <p>
 * The view reports a new grid on every layout pass: once per frame while the keyboard animates,
 * while a pop-up window edge is dragged, at each pinch-zoom step. Each pty resize makes the kernel
 * send SIGWINCH, and full-screen apps that keep their own viewport (tmux panes, Codex / Claude Code
 * full screen) re-anchor on every one; a burst of intermediate sizes leaves them drawn in only part
 * of the screen. This applies the size once the changes stop: {@link #request} restarts a short
 * timer and only the latest size reaches the pty, and never one equal to the size it already has.
 * <p>
 * The emulator grid itself still resizes at once, so rendering stays in step with the view; only
 * the pty (what the program reads through TIOCGWINSZ) lags by {@link #DELAY_MS}.
 * Not thread-safe: call it from one thread (the main thread, as TerminalSession does).
 */
public final class PtySizeCoalescer {

    public static final long DELAY_MS = 120;

    public interface Scheduler {
        void postDelayed(Runnable task, long delayMs);

        void cancel(Runnable task);
    }

    public interface Sink {
        void apply(int columns, int rows);
    }

    private final Scheduler mScheduler;
    private final Sink mSink;
    private final long mDelayMs;
    private int mAppliedColumns;
    private int mAppliedRows;
    private int mPendingColumns;
    private int mPendingRows;
    private boolean mPending;
    private final Runnable mFlush = this::flush;

    /** {@code columns} x {@code rows} is the size the pty already has (it was created with it). */
    public PtySizeCoalescer(Scheduler scheduler, Sink sink, long delayMs, int columns, int rows) {
        mScheduler = scheduler;
        mSink = sink;
        mDelayMs = delayMs;
        mAppliedColumns = columns;
        mAppliedRows = rows;
    }

    public void request(int columns, int rows) {
        mPendingColumns = columns;
        mPendingRows = rows;
        mPending = true;
        mScheduler.cancel(mFlush);
        mScheduler.postDelayed(mFlush, mDelayMs);
    }

    /** Drops a pending size, e.g. once the pty is closed. */
    public void cancel() {
        mPending = false;
        mScheduler.cancel(mFlush);
    }

    void flush() {
        if (!mPending) return;
        mPending = false;
        if (mPendingColumns == mAppliedColumns && mPendingRows == mAppliedRows) return;
        mAppliedColumns = mPendingColumns;
        mAppliedRows = mPendingRows;
        mSink.apply(mAppliedColumns, mAppliedRows);
    }
}
