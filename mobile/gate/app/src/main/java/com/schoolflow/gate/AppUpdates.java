package com.schoolflow.gate;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.widget.Toast;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

final class AppUpdates {
    private static final String DOWNLOAD_PREFIX =
            "https://github.com/irfanmehmood5703-web/SchoolFlow/releases/download/qr-attendance-";

    static void check(Activity activity) {
        new Thread(() -> {
            try {
                JSONObject info = readManifest();
                int version = info.optInt("version_code");
                String link = info.optString("url");
                String label = info.optString("version_name");
                if (!info.optBoolean("available") || version <= BuildConfig.VERSION_CODE
                        || !validLink(link, version) || !label.matches("[0-9]+(?:\\.[0-9]+){1,3}")) {
                    return;
                }
                activity.runOnUiThread(() -> {
                    if (activity.isFinishing() || activity.isDestroyed()) return;
                    new AlertDialog.Builder(activity)
                            .setTitle("Update available")
                            .setMessage("QR Attendance " + label + " is ready to install.")
                            .setNegativeButton("Later", null)
                            .setPositiveButton("Update", (dialog, button) -> openDownload(activity, link))
                            .show();
                });
            } catch (IOException | JSONException ignored) {
                // The gate can still mark attendance if the update check fails.
            }
        }, "qr-attendance-update").start();
    }

    static boolean validLink(String link, int version) {
        String prefix = DOWNLOAD_PREFIX + version + "-";
        return link.startsWith(prefix)
                && link.substring(prefix.length()).matches("[0-9]+-[0-9]+/SchoolFlow-QR-Attendance\\.apk");
    }

    private static JSONObject readManifest() throws IOException, JSONException {
        URL url = new URL(EndpointPolicy.BASE + "/api/mobile-app/update/qr-attendance");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) return new JSONObject();
            try (InputStream input = connection.getInputStream()) {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] buffer = new byte[1024];
                for (int bytes; (bytes = input.read(buffer)) != -1;) {
                    if (output.size() + bytes > 8192) throw new IOException("Update response too large");
                    output.write(buffer, 0, bytes);
                }
                return new JSONObject(output.toString(StandardCharsets.UTF_8.name()));
            }
        } finally {
            connection.disconnect();
        }
    }

    private static void openDownload(Activity activity, String link) {
        try {
            activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(link)));
        } catch (ActivityNotFoundException unavailable) {
            Toast.makeText(activity, "Open General → App Links in SchoolFlow to download the update.", Toast.LENGTH_LONG).show();
        }
    }

    private AppUpdates() {}
}
