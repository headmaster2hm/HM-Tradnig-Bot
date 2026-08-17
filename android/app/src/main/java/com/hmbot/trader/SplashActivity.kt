package com.hmbot.trader

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.appcompat.app.AppCompatActivity
import com.hmbot.trader.databinding.ActivitySplashBinding

class SplashActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySplashBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySplashBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val prefs = getSharedPreferences("hmbot", MODE_PRIVATE)
        val savedKey = prefs.getString("license_key", "") ?: ""
        val savedAccount = prefs.getString("mt5_account", "") ?: ""

        Handler(Looper.getMainLooper()).postDelayed({
            if (savedKey.isNotEmpty() && savedAccount.isNotEmpty()) {
                startActivity(Intent(this, MainActivity::class.java))
            } else {
                startActivity(Intent(this, LoginActivity::class.java))
            }
            finish()
        }, 2000)
    }
}
