# Moshi reflective adapters used in this scaffold; keep DTO classes.
-keep class gt.polityk.forecast.data.api.** { *; }

# Retrofit / OkHttp standard rules.
-dontwarn okio.**
-dontwarn javax.annotation.**
-keep class kotlin.Metadata { *; }
