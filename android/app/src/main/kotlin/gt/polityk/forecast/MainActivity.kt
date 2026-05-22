package gt.polityk.forecast

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import dagger.hilt.android.AndroidEntryPoint
import gt.polityk.forecast.ui.PolitykScaffold
import gt.polityk.forecast.ui.theme.PolitykTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            PolitykTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    PolitykScaffold()
                }
            }
        }
    }
}
