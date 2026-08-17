package com.hmbot.trader

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import com.hmbot.trader.databinding.ActivityLoginBinding
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnActivate.setOnClickListener {
            val key = binding.inputKey.text.toString().trim()
            val account = binding.inputAccount.text.toString().trim()

            if (key.isEmpty()) {
                binding.inputKey.error = "Enter your license key"
                return@setOnClickListener
            }
            if (account.isEmpty()) {
                binding.inputAccount.error = "Enter your MT5 account number"
                return@setOnClickListener
            }

            setLoading(true)
            activateLicense(key, account)
        }
    }

    private fun activateLicense(key: String, account: String) {
        executor.execute {
            try {
                val url = URL("${BuildConfig.SERVER_URL}/api/license/activate")
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    setRequestProperty("Content-Type", "application/json")
                    doOutput = true
                    connectTimeout = 15000
                    readTimeout = 15000
                }

                val body = JSONObject().apply {
                    put("key", key)
                    put("mt5_account", account)
                }

                OutputStreamWriter(conn.outputStream).use { it.write(body.toString()) }

                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val response = BufferedReader(InputStreamReader(stream)).use { it.readText() }
                val json = JSONObject(response)

                handler.post {
                    if (json.optBoolean("ok", false)) {
                        saveCredentials(key, account)
                        startActivity(Intent(this, MainActivity::class.java))
                        finish()
                    } else {
                        setLoading(false)
                        showError(json.optString("error", "Activation failed"))
                    }
                }
            } catch (e: Exception) {
                handler.post {
                    setLoading(false)
                    showError("Network error — check your connection")
                }
            }
        }
    }

    private fun saveCredentials(key: String, account: String) {
        getSharedPreferences("hmbot", MODE_PRIVATE).edit().apply {
            putString("license_key", key)
            putString("mt5_account", account)
            apply()
        }
    }

    private fun setLoading(loading: Boolean) {
        binding.btnActivate.isEnabled = !loading
        binding.btnActivate.text = if (loading) "Activating..." else "Activate & Enter"
        binding.progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        binding.inputKey.isEnabled = !loading
        binding.inputAccount.isEnabled = !loading
    }

    private fun showError(msg: String) {
        binding.errorText.text = msg
        binding.errorText.visibility = View.VISIBLE
    }
}
