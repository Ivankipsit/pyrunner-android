package com.pyrunner.app.runs

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.pyrunner.app.MainActivity
import com.pyrunner.app.R

class RunService : Service() {
    lateinit var engine: RunEngine
        private set

    private val binder = LocalBinder()
    private var wake: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        engine = RunEngine(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_FOREGROUND && ::engine.isInitialized) {
            showForeground(engine.activeCount().coerceAtLeast(1))
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onDestroy() {
        if (::engine.isInitialized) engine.closed = true
        releaseWake()
        super.onDestroy()
    }

    fun ensureForeground(active: Int) {
        val intent = Intent(this, RunService::class.java).setAction(ACTION_FOREGROUND)
        ContextCompat.startForegroundService(this, intent)
        val show = Runnable { showForeground(active.coerceAtLeast(1)) }
        if (Looper.myLooper() == Looper.getMainLooper()) show.run() else mainHandler().post(show)
    }

    fun demote() {
        val block = Runnable {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            releaseWake()
            if (::engine.isInitialized && !engine.clientAttached && engine.activeCount() == 0) {
                stopSelf()
            }
        }
        if (Looper.myLooper() == Looper.getMainLooper()) block.run() else mainHandler().post(block)
    }

    private fun showForeground(active: Int) {
        val type = if (Build.VERSION.SDK_INT >= 34) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(active), type)
        acquireWake()
    }

    private fun buildNotification(active: Int) = NotificationCompat.Builder(this, CHANNEL)
        .setSmallIcon(R.drawable.ic_stat)
        .setContentTitle("PyRunner")
        .setContentText(if (active == 1) "1 script running" else "$active scripts running")
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setContentIntent(openIntent())
        .build()

    private fun openIntent(): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val channel = NotificationChannel(CHANNEL, "Script runs", NotificationManager.IMPORTANCE_LOW)
        channel.description = "Shows Python scripts you started"
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun acquireWake() {
        val lock = wake ?: (getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "pyrunner:runs",
        ).also {
            it.setReferenceCounted(false)
            wake = it
        }
        if (!lock.isHeld) lock.acquire(12 * 60 * 60 * 1000L)
    }

    private fun releaseWake() {
        val lock = wake ?: return
        if (lock.isHeld) lock.release()
    }

    private fun mainHandler() = android.os.Handler(Looper.getMainLooper())

    inner class LocalBinder : Binder() {
        fun service(): RunService = this@RunService
    }

    companion object {
        const val ACTION_FOREGROUND = "com.pyrunner.app.FOREGROUND"
        private const val CHANNEL = "runs"
        private const val NOTIFICATION_ID = 41
    }
}
