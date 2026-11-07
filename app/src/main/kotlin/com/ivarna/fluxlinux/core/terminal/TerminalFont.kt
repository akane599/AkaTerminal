package com.ivarna.fluxlinux.core.terminal

import android.content.Context
import android.graphics.Paint
import android.graphics.Typeface
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File

/**
 * The terminal's typeface: the bundled JetBrainsMono Nerd Font, or a font file the user picked
 * in Terminal settings (copied into app storage, so the source can go away).
 */
object TerminalFont {

    private const val BUNDLED_ASSET = "fonts/font.ttf"
    private const val PREFS_NAME = "flux_terminal_prefs"
    private const val KEY_CUSTOM_NAME = "custom_font_name"

    /** Character widths compared by [isMonospace]: narrow, wide and punctuation glyphs. */
    const val PROBE_CHARS = "iWm.l0_"

    /** Nerd Fonts are a few MB; anything this big isn't a font worth copying into app storage. */
    private const val MAX_FONT_BYTES = 50L * 1024 * 1024

    sealed interface ImportResult {
        data object Ok : ImportResult
        data object Unreadable : ImportResult
        data object NotMonospace : ImportResult
    }

    @Volatile
    private var cache: Pair<String, Typeface>? = null

    private fun customFile(ctx: Context) = File(ctx.filesDir, "terminal/font.ttf")

    private fun prefs(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** Display name of the picked font, or null when the bundled one is in use. */
    fun customName(ctx: Context): String? =
        if (customFile(ctx).isFile) prefs(ctx).getString(KEY_CUSTOM_NAME, null) ?: "font.ttf" else null

    /**
     * The typeface to draw with. Same instance until the font changes, so callers can compare
     * by identity before calling TerminalView.setTypeface (which re-lays out the grid).
     */
    fun load(ctx: Context): Typeface {
        val file = customFile(ctx)
        val key = if (file.isFile) "custom:${file.lastModified()}:${file.length()}" else "bundled"
        cache?.let { (k, tf) -> if (k == key) return tf }
        val typeface = (if (file.isFile) fromFile(file) else null) ?: bundled(ctx)
        cache = key to typeface
        return typeface
    }

    private fun bundled(ctx: Context): Typeface =
        runCatching { Typeface.createFromAsset(ctx.assets, BUNDLED_ASSET) }.getOrDefault(Typeface.MONOSPACE)

    /** Null when Android can't parse the file or the font isn't monospace. */
    private fun fromFile(file: File): Typeface? =
        runCatching { Typeface.Builder(file).build() }.getOrNull()?.takeIf(::isMonospaceTypeface)

    private fun isMonospaceTypeface(typeface: Typeface): Boolean {
        val paint = Paint().apply {
            this.typeface = typeface
            textSize = 48f
        }
        return isMonospace(FloatArray(PROBE_CHARS.length) { paint.measureText(PROBE_CHARS, it, it + 1) })
    }

    /** True when every width is within 1 % of the first (a terminal grid needs one cell width). */
    fun isMonospace(widths: FloatArray): Boolean {
        if (widths.isEmpty()) return false
        val first = widths[0]
        if (first <= 0f) return false
        return widths.all { kotlin.math.abs(it - first) <= first * 0.01f }
    }

    /** Copies [uri] in and validates it; call off the main thread. Keeps the old font on failure. */
    fun import(ctx: Context, uri: Uri): ImportResult {
        val target = customFile(ctx)
        target.parentFile?.mkdirs()
        val staging = File(target.parentFile, "font.ttf.new")
        try {
            val copied = ctx.contentResolver.openInputStream(uri)?.use { input ->
                staging.outputStream().use { out ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        total += n
                        if (total > MAX_FONT_BYTES) return ImportResult.Unreadable
                        out.write(buffer, 0, n)
                    }
                }
                true
            } ?: false
            if (!copied || staging.length() == 0L) return ImportResult.Unreadable
            val typeface = runCatching { Typeface.Builder(staging).build() }.getOrNull()
                ?: return ImportResult.Unreadable
            if (!isMonospaceTypeface(typeface)) return ImportResult.NotMonospace
            if (!staging.renameTo(target)) return ImportResult.Unreadable
            prefs(ctx).edit().putString(KEY_CUSTOM_NAME, displayName(ctx, uri)).apply()
            return ImportResult.Ok
        } catch (_: Exception) {
            return ImportResult.Unreadable
        } finally {
            staging.delete()
        }
    }

    /** Back to the bundled JetBrainsMono Nerd Font. */
    fun reset(ctx: Context) {
        customFile(ctx).delete()
        prefs(ctx).edit().remove(KEY_CUSTOM_NAME).apply()
    }

    private fun displayName(ctx: Context, uri: Uri): String? = runCatching {
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) it.getString(0) else null
        }
    }.getOrNull()
}
