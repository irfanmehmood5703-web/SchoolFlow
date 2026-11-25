package com.schoolflow.clients;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class AppUpdates {
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static final long RETRY_DELAY_MS = 5_000;
    private final Activity activity;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable retry = () -> check(false);
    private boolean foreground;
    private boolean checking;
    private int lastPrompt;

    AppUpdates(Activity activity) {
        this.activity = activity;
    }

    void resume() {
        foreground = true;
        check(true);
    }

    void pause() {
        foreground = false;
        main.removeCallbacks(retry);
    }

    private void check(boolean retryOnFailure) {
        if (!foreground || checking || BuildConfig.SCHOOL_SCOPE.isEmpty()) return;
        checking = true;
        WORKER.execute(() -> {
            JSONObject info;
            try {
                info = loadRelease();
            } catch (Exception error) {
                main.post(() -> {
                    checking = false;
                    if (foreground && retryOnFailure) main.postDelayed(retry, RETRY_DELAY_MS);
                });
                return;
            }

            main.post(() -> {
                checking = false;
                if (foreground && !activity.isFinishing() && !activity.isDestroyed()) show(info);
            });
        });
    }

    private JSONObject loadRelease() throws Exception {
        String endpoint = EndpointPolicy.BASE + "/api/mobile-app/update/" + BuildConfig.SCHOOL_SCOPE + "/" + BuildConfig.ROLE;
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setConnectTimeout(12_000);
        connection.setReadTimeout(12_000);
        try {
            if (connection.getResponseCode() != 200) throw new IOException("Update feed is unavailable");
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                byte[] bytes = new byte[2048];
                for (int count; (count = input.read(bytes)) != -1; ) {
                    if (out.size() + count > 8192) throw new IOException("Update feed exceeds the size limit");
                    out.write(bytes, 0, count);
                }
            }
            return new JSONObject(out.toString("UTF-8"));
        } finally {
            connection.disconnect();
        }
    }

    private void show(JSONObject info) {
        int latest = info.optInt("version_code");
        if (!info.optBoolean("available") || latest <= lastPrompt) return;
        PackageInfo app;
        try {
            app = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
        } catch (android.content.pm.PackageManager.NameNotFoundException error) {
            return;
        }
        long installed = Build.VERSION.SDK_INT >= 28 ? app.getLongVersionCode() : app.versionCode;
        String link = info.optString("url");
        if (latest <= installed || !link.startsWith(EndpointPolicy.BASE + "/apps/school/")
                || !link.endsWith("/" + BuildConfig.ROLE + ".apk")) return;

        String latestLabel = info.optString("version_name", "School build " + latest);
        String changes = info.optString("whats_new", "Improvements and fixes for your school app.");
        boolean required = installed < info.optInt("minimum_supported_version_code");

        AlertDialog.Builder dialog = new AlertDialog.Builder(activity)
                .setTitle(required ? "Update required" : "Update available")
                .setMessage("Installed: " + app.versionName + " (" + installed + ")\nLatest: " + latestLabel
                        + " (" + latest + ")\n\nWhat's new\n" + changes)
                .setPositiveButton("UPDATE", (d, w) -> {
                    try {
                        activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(link)));
                    } catch (ActivityNotFoundException error) {
                        lastPrompt = 0;
                        Toast.makeText(activity, "Open General → App Links in your school portal to update.",
                                Toast.LENGTH_LONG).show();
                    }
                });
        if (required) {
            dialog.setNegativeButton("EXIT", (d, w) -> activity.finishAffinity()).setCancelable(false);
        } else {
            dialog.setNegativeButton("LATER", null);
        }
        lastPrompt = latest;
        dialog.show();
    }
}
