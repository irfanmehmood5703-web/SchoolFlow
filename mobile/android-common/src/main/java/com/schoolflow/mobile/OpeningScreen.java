package com.schoolflow.mobile;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/**
 * Locally rendered, opaque startup screen, independent of the network and WebView.
 * Only an unauthenticated, read-only health GET is retried; no school action is replayed.
 */
public final class OpeningScreen {
    private static final int GREEN = 0xff145c46, INK = 0xff173a2e, MUTED = 0xff61766b;
    private final Activity activity;
    private final View content;
    private final FrameLayout shield;
    private final TextView title, message;
    private final ProgressBar progress;
    private final Button retry, offline;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private Future<?> work;
    private Runnable deadline;
    private int generation;
    private boolean closed;

    public OpeningScreen(Activity activity, View content) {
        this.activity = activity;
        this.content = content;
        FrameLayout root = new FrameLayout(activity);
        root.addView(content, new FrameLayout.LayoutParams(-1, -1));
        shield = new FrameLayout(activity);
        shield.setBackgroundColor(0xffeff6f2);
        shield.setClickable(true);
        shield.setFocusable(true);
        shield.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(true);
        LinearLayout panel = new LinearLayout(activity);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setPadding(dp(24), dp(24), dp(24), dp(24));
        ImageView logo = new ImageView(activity);
        logo.setImageDrawable(activity.getApplicationInfo().loadIcon(activity.getPackageManager()));
        logo.setContentDescription("School logo");
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        GradientDrawable tile = new GradientDrawable();
        tile.setColor(Color.WHITE);
        tile.setCornerRadius(dp(24));
        logo.setBackground(tile);
        logo.setPadding(dp(12), dp(12), dp(12), dp(12));
        panel.addView(logo, new LinearLayout.LayoutParams(dp(94), dp(94)));
        TextView brand = label(activity.getApplicationInfo().loadLabel(activity.getPackageManager()).toString(), 24, INK, true);
        brand.setPadding(0, dp(20), 0, dp(8));
        panel.addView(brand, new LinearLayout.LayoutParams(-1, -2));
        title = label("Opening your school app", 19, GREEN, true);
        panel.addView(title, new LinearLayout.LayoutParams(-1, -2));
        progress = new ProgressBar(activity);
        progress.setIndeterminateTintList(ColorStateList.valueOf(GREEN));
        LinearLayout.LayoutParams spinner = new LinearLayout.LayoutParams(dp(44), dp(44));
        spinner.topMargin = dp(24); spinner.bottomMargin = dp(16);
        panel.addView(progress, spinner);
        message = label("Getting your school workspace ready…", 15, MUTED, false);
        message.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        panel.addView(message, new LinearLayout.LayoutParams(-1, -2));
        retry = new Button(activity);
        retry.setText("Try again"); retry.setAllCaps(false);
        retry.setTextColor(Color.WHITE);
        retry.setBackgroundTintList(ColorStateList.valueOf(GREEN));
        LinearLayout.LayoutParams action = new LinearLayout.LayoutParams(-2, -2);
        action.topMargin = dp(16);
        panel.addView(retry, action);
        offline = new Button(activity);
        offline.setText("Open app without connection"); offline.setAllCaps(false);
        panel.addView(offline, new LinearLayout.LayoutParams(-2, -2));
        TextView footer = label("Powered by SchoolFlow", 12, MUTED, true);
        footer.setPadding(0, dp(28), 0, 0);
        panel.addView(footer);
        scroll.addView(panel, new ScrollView.LayoutParams(-1, -1));
        shield.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        root.addView(shield, new FrameLayout.LayoutParams(-1, -1));
        activity.setContentView(root);
        show();
    }

    private int dp(int n) { return Math.round(n * activity.getResources().getDisplayMetrics().density); }
    private TextView label(String text, int size, int color, boolean bold) {
        TextView view = new TextView(activity);
        view.setText(text); view.setTextSize(size); view.setTextColor(color);
        view.setGravity(Gravity.CENTER);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    public boolean visible() { return shield.getVisibility() == View.VISIBLE; }
    public void show() {
        if (closed) return;
        content.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        shield.setVisibility(View.VISIBLE);
        title.setText("Opening your school app");
        message.setText("Getting your school workspace ready…");
        retry.setVisibility(View.GONE);
        offline.setVisibility(View.GONE);
        progress.setVisibility(View.VISIBLE);
    }
    public void dismiss() {
        cancelProbe();
        shield.setVisibility(View.GONE);
        content.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
    }
    public void unavailable(String detail, Runnable again, Runnable openOffline) {
        cancelProbe();
        show();
        title.setText("Your school app is not ready yet");
        message.setText(detail);
        progress.setVisibility(View.GONE);
        retry.setVisibility(View.VISIBLE);
        retry.setOnClickListener(v -> again.run());
        if (openOffline != null) {
            offline.setVisibility(View.VISIBLE);
            offline.setOnClickListener(v -> { dismiss(); openOffline.run(); });
        }
    }

    public void awaitReady(String base, Runnable ready, Runnable openOffline) {
        cancelProbe();
        if (closed) return;
        show();
        final int ticket = generation;
        final long until = SystemClock.elapsedRealtime() + ReadinessPolicy.WAIT_MS;
        Runnable fail = () -> unavailable("The connection is taking longer than usual. Check your internet and try again.",
                () -> awaitReady(base, ready, openOffline), openOffline);
        deadline = () -> { if (current(ticket)) fail.run(); };
        ui.postDelayed(deadline, ReadinessPolicy.WAIT_MS);
        work = worker.submit(() -> {
            while (!Thread.currentThread().isInterrupted() && SystemClock.elapsedRealtime() < until) {
                if (probe(base, until)) {
                    ui.post(() -> {
                        if (!current(ticket)) return;
                        cancelProbe();
                        message.setText("Connected. Opening your school app…");
                        ready.run();
                    });
                    return;
                }
                ui.post(() -> {
                    if (current(ticket)) message.setText("Still connecting to your school. Please wait…");
                });
                try { Thread.sleep(ReadinessPolicy.RETRY_MS); }
                catch (InterruptedException stopped) { Thread.currentThread().interrupt(); return; }
            }
            ui.post(() -> { if (current(ticket)) fail.run(); });
        });
    }

    private boolean current(int ticket) {
        return !closed && ticket == generation && !activity.isFinishing() && !activity.isDestroyed();
    }
    private void cancelProbe() {
        generation++;
        if (deadline != null) { ui.removeCallbacks(deadline); deadline = null; }
        if (work != null) { work.cancel(true); work = null; }
    }
    private static boolean probe(String base, long until) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(base + "/healthz");
            if (!"https".equals(url.getProtocol()) || url.getUserInfo() != null) return false;
            int timeout = (int)Math.max(1L, Math.min(ReadinessPolicy.REQUEST_MS, until - SystemClock.elapsedRealtime()));
            connection = (HttpURLConnection)url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(timeout);
            connection.setReadTimeout(timeout);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-cache, no-store");
            int code = connection.getResponseCode();
            String type = connection.getContentType(), marker = connection.getHeaderField("X-SchoolFlow-Response");
            if (code != 200 || type == null || !type.toLowerCase(java.util.Locale.ROOT).contains("application/json") || !"1".equals(marker)) return false;
            try (InputStream input = connection.getInputStream()) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[1024];
                for (int n; (n = input.read(buffer)) != -1;) {
                    if (bytes.size() + n > 8192 || Thread.currentThread().isInterrupted()
                            || SystemClock.elapsedRealtime() >= until) return false;
                    bytes.write(buffer, 0, n);
                }
                JSONObject result = new JSONObject(bytes.toString("UTF-8"));
                return ReadinessPolicy.health(code, type, marker, result.optString("status"), result.optString("build"));
            }
        } catch (Exception notReady) { return false; }
        finally { if (connection != null) connection.disconnect(); }
    }

    public void close() {
        closed = true;
        cancelProbe();
        ui.removeCallbacksAndMessages(null);
        worker.shutdownNow();
    }
}
