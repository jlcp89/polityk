package gt.polityk.forecast.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Paper = Color(0xFFFAF6EE)
private val Ink = Color(0xFF1F1A14)
private val InkSoft = Color(0xFF4A4239)
private val Accent = Color(0xFFC66A4B)
private val AccentSoft = Color(0xFFF3E0D6)
private val Line = Color(0xFFE5DCCC)

private val LightColors =
    lightColorScheme(
        primary = Accent,
        onPrimary = Color.White,
        primaryContainer = AccentSoft,
        onPrimaryContainer = Ink,
        secondary = InkSoft,
        onSecondary = Paper,
        background = Paper,
        onBackground = Ink,
        surface = Paper,
        onSurface = Ink,
        surfaceVariant = Line,
        onSurfaceVariant = InkSoft,
        outline = Line,
    )

private val DarkColors =
    darkColorScheme(
        primary = AccentSoft,
        onPrimary = Ink,
        primaryContainer = Accent,
        onPrimaryContainer = Paper,
        background = Color(0xFF1D1814),
        onBackground = Paper,
        surface = Color(0xFF1D1814),
        onSurface = Paper,
    )

@Composable
fun PolitykTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) DarkColors else LightColors
    MaterialTheme(
        colorScheme = colors,
        content = content,
    )
}
