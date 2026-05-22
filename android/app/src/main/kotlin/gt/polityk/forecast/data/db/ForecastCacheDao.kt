package gt.polityk.forecast.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface ForecastCacheDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: ForecastCacheEntity)

    /**
     * Provided for issue #42 (freshness banner). The current issue scaffolds
     * writes only; reads exist for testing but are not consumed by the UI yet.
     */
    @Query("SELECT * FROM forecast_cache WHERE endpointUrl = :url LIMIT 1")
    suspend fun get(url: String): ForecastCacheEntity?

    @Query("DELETE FROM forecast_cache WHERE endpointUrl = :url")
    suspend fun deleteByEndpoint(url: String)

    @Query("DELETE FROM forecast_cache")
    suspend fun clear()
}
