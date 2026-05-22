package gt.polityk.forecast.data.db

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [ForecastCacheEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class PolitykDatabase : RoomDatabase() {
    abstract fun forecastCacheDao(): ForecastCacheDao
}
