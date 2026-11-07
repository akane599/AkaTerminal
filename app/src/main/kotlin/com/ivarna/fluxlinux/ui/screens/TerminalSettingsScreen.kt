package com.ivarna.fluxlinux.ui.screens

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.sharp.Add
import androidx.compose.material.icons.sharp.Remove
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import com.ivarna.fluxlinux.R
import com.ivarna.fluxlinux.core.terminal.GuestLoginShell
import com.ivarna.fluxlinux.core.terminal.TerminalFont
import com.ivarna.fluxlinux.core.utils.TerminalPreferences
import com.ivarna.fluxlinux.ui.components.aka.AkaButton
import com.ivarna.fluxlinux.ui.components.aka.AkaButtonKind
import com.ivarna.fluxlinux.ui.components.aka.SectionLabel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import com.ivarna.fluxlinux.ui.theme.CodeStyle
import com.ivarna.fluxlinux.ui.theme.FluxSpacing

/**
 * Terminal font zoom + ExtraKeys toolbar + guest login shell (nativecode settings parity).
 */
@Composable
fun TerminalSettingsScreen(
    onBack: () -> Unit = {}
) {
    val context = LocalContext.current
    var fontSize by remember {
        mutableIntStateOf(TerminalPreferences.getFontSize(context))
    }
    var showExtraKeys by remember {
        mutableStateOf(TerminalPreferences.isExtraKeysEnabled(context))
    }
    var accelerateKeys by remember {
        mutableStateOf(TerminalPreferences.isKeyRepeatAccelerated(context))
    }
    var guestShellZsh by remember {
        mutableStateOf(TerminalPreferences.preferZsh(context))
    }
    var legacyProot by remember {
        mutableStateOf(TerminalPreferences.isLegacyProotLauncher(context))
    }
    var customFont by remember { mutableStateOf(TerminalFont.customName(context)) }
    var importingFont by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val fontPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        importingFont = true
        scope.launch {
            val result = withContext(Dispatchers.IO) { TerminalFont.import(context, uri) }
            importingFont = false
            customFont = TerminalFont.customName(context)
            val message = when (result) {
                TerminalFont.ImportResult.Ok -> R.string.terminal_settings_font_ok
                TerminalFont.ImportResult.Unreadable -> R.string.terminal_settings_font_unreadable
                TerminalFont.ImportResult.NotMonospace -> R.string.terminal_settings_font_not_monospace
            }
            Toast.makeText(context, message, Toast.LENGTH_LONG).show()
        }
    }

    SettingsPageScaffold(title = "Terminal", onBack = onBack) {
        SectionLabel(stringResource(R.string.settings_aka_terminal_text))
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = FluxSpacing.lg, vertical = FluxSpacing.sm)
        ) {
            Text(
                "Global terminal zoom",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                "Font size for the embedded terminal (pinch zoom also updates this).",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = FluxSpacing.lg, vertical = FluxSpacing.sm),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            val stepperColors = IconButtonDefaults.filledTonalIconButtonColors(
                containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                contentColor = MaterialTheme.colorScheme.onSurface,
            )
            val canDecrease = fontSize > TerminalPreferences.FONT_MIN
            FilledTonalIconButton(
                onClick = {
                    val next = (fontSize - 2).coerceAtLeast(TerminalPreferences.FONT_MIN)
                    fontSize = next
                    TerminalPreferences.setFontSize(context, next)
                },
                enabled = canDecrease,
                shape = MaterialTheme.shapes.small,
                colors = stepperColors,
            ) {
                Icon(Icons.Sharp.Remove, contentDescription = "Smaller")
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    "${fontSize} pt",
                    style = CodeStyle.copy(
                        fontSize = MaterialTheme.typography.headlineSmall.fontSize,
                        lineHeight = MaterialTheme.typography.headlineSmall.lineHeight,
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
                )
                Text(
                    "Range ${TerminalPreferences.FONT_MIN}–${TerminalPreferences.FONT_MAX}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            val canIncrease = fontSize < TerminalPreferences.FONT_MAX
            FilledTonalIconButton(
                onClick = {
                    val next = (fontSize + 2).coerceAtMost(TerminalPreferences.FONT_MAX)
                    fontSize = next
                    TerminalPreferences.setFontSize(context, next)
                },
                enabled = canIncrease,
                shape = MaterialTheme.shapes.small,
                colors = stepperColors,
            ) {
                Icon(Icons.Sharp.Add, contentDescription = "Larger")
            }
        }

        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = FluxSpacing.lg, vertical = FluxSpacing.sm)
        ) {
            Text(
                stringResource(R.string.terminal_settings_font),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                customFont?.let { stringResource(R.string.terminal_settings_font_custom, it) }
                    ?: stringResource(R.string.terminal_settings_font_bundled),
                style = CodeStyle,
                color = MaterialTheme.colorScheme.secondary
            )
            Text(
                stringResource(R.string.terminal_settings_font_summary),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        // Stacked: two labelled buttons side by side don't fit a 360dp phone.
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = FluxSpacing.lg, vertical = FluxSpacing.sm),
            verticalArrangement = Arrangement.spacedBy(FluxSpacing.sm)
        ) {
            AkaButton(
                text = stringResource(R.string.terminal_settings_font_choose),
                onClick = {
                    // Many file managers label fonts application/octet-stream; import() validates.
                    fontPicker.launch(arrayOf("font/*", "application/x-font-ttf", "application/x-font-otf", "application/font-sfnt", "application/vnd.ms-opentype", "application/octet-stream"))
                },
                enabled = !importingFont,
                kind = AkaButtonKind.SECONDARY,
            )
            if (customFont != null) {
                AkaButton(
                    text = stringResource(R.string.terminal_settings_font_reset),
                    onClick = {
                        TerminalFont.reset(context)
                        customFont = null
                    },
                    enabled = !importingFont,
                    kind = AkaButtonKind.SECONDARY,
                )
            }
        }

        SectionLabel(stringResource(R.string.settings_aka_terminal_keyboard))
        TerminalSwitchSettingCard(
            title = "Extra keyboard rows",
            description = "Show CTRL, ALT, ESC, arrows and symbols under the terminal.",
            checked = showExtraKeys,
            onCheckedChange = {
                showExtraKeys = it
                TerminalPreferences.setExtraKeysEnabled(context, it)
            }
        )
        TerminalSwitchSettingCard(
            title = stringResource(R.string.terminal_settings_accelerate_keys),
            description = stringResource(R.string.terminal_settings_accelerate_keys_summary),
            checked = accelerateKeys,
            onCheckedChange = {
                accelerateKeys = it
                TerminalPreferences.setKeyRepeatAccelerated(context, it)
            }
        )

        SectionLabel(stringResource(R.string.settings_aka_terminal_shell))
        SettingsPageSwitchRow(
            title = "Guest login shell",
            supporting = "On = zsh, off = bash. New proot/chroot Terminal sessions only; live tabs keep their shell.",
            checked = guestShellZsh,
            onCheckedChange = { on ->
                guestShellZsh = on
                TerminalPreferences.setGuestLoginShell(
                    context,
                    if (on) GuestLoginShell.ZSH else GuestLoginShell.BASH
                )
            },
            description = "Guest login shell: ${if (guestShellZsh) "zsh" else "bash"}",
            trailingExtra = {
                Text(
                    text = if (guestShellZsh) "zsh" else "bash",
                    style = CodeStyle,
                    color = MaterialTheme.colorScheme.secondary,
                    modifier = Modifier.padding(end = FluxSpacing.md)
                )
            }
        )
        SettingsPageSwitchRow(
            title = "Legacy proot launcher",
            supporting = "Open proot terminals through proot-distro (python). Slower; use only if the default launch fails.",
            checked = legacyProot,
            onCheckedChange = {
                legacyProot = it
                TerminalPreferences.setLegacyProotLauncher(context, it)
            },
            description = "Legacy proot launcher"
        )
    }
}

/**
 * Title + one-line description + switch: this screen's toggle row (a full-width row on the
 * stock; the name is historical).
 */
@Composable
fun TerminalSwitchSettingCard(
    title: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    SettingsPageSwitchRow(
        title = title,
        supporting = description,
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = modifier,
    )
}
