package gt.polityk.forecast.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import gt.polityk.forecast.data.db.ForecastCacheDao
import gt.polityk.forecast.data.db.PolitykDatabase
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides
    @Singleton
    fun providePolitykDatabase(
        @ApplicationContext context: Context,
    ): PolitykDatabase =
        Room.databaseBuilder(
            context,
            PolitykDatabase::class.java,
            "polityk.db",
        ).build()

    @Provides
    @Singleton
    fun provideForecastCacheDao(db: PolitykDatabase): ForecastCacheDao = db.forecastCacheDao()
}
