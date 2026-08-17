# HM Bot Trader - ProGuard rules
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.hmbot.trader.** { *; }
-dontwarn android.webkit.**
