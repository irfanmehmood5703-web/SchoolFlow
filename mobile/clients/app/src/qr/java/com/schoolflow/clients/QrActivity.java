package com.schoolflow.clients;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.KeyguardManager;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import com.schoolflow.mobile.PullToRefresh;
import com.schoolflow.mobile.OpeningScreen;
import com.schoolflow.mobile.PasswordVisibility;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

public final class QrActivity extends Activity {
    private static final int UNLOCK = 84;
    private static final String QR = "schoolflow:(student|employee):[a-f0-9]{64}";
    private static final String KEY = "[A-Za-z0-9_-]{40,60}";
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AppUpdates updates = new AppUpdates(this);
    private OpeningScreen opening;
    private JSONObject data;
    private Vault vault;
    private TextView status;
    private Spinner direction;
    private Button scan, retry, connect;
    private boolean busy;
    private String scanningDirection;
    private QrVoiceFeedback feedback;
    private boolean foreground,opened;
    private record Announcement(String name, boolean alreadyMarked) {}
    private Announcement pendingAnnouncement;
    private Announcement savedScanAnnouncement;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(0xff176b4a);
        getWindow().setNavigationBarColor(0xff176b4a);
        if (saved != null) scanningDirection = saved.getString("direction");
        ScrollView scroll = new ScrollView(this);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(24), dp(20), dp(20));
        content.setBackgroundColor(0xfff3f8f5);
        scroll.addView(content);
        ImageView logo = new ImageView(this);
        logo.setImageDrawable(getApplicationInfo().loadIcon(getPackageManager()));
        content.addView(logo, new LinearLayout.LayoutParams(dp(54), dp(54)));
        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextSize(25);
        title.setTextColor(0xff164e3d);
        title.setPadding(0, dp(12), 0, dp(16));
        content.addView(title);
        TextView instruction = new TextView(this);
        instruction.setText("Choose IN or OUT, then scan a student or staff QR card.");
        content.addView(instruction);
        direction = new Spinner(this);
        direction.setContentDescription("Attendance direction");
        direction.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"IN", "OUT"}));
        content.addView(direction);
        scan = button(content, "Scan QR card", this::openScanner);
        retry = button(content, "Retry pending scan", () -> run(this::deliver));
        connect = button(content, "Connection settings", this::unlock);
        button(content, "Test voice / sound", () -> feedback.confirm("", true, false));
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        status = new TextView(this);
        status.setTextColor(Color.DKGRAY);
        status.setPadding(0, dp(12), 0, 0);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        content.addView(status);
        opening = new OpeningScreen(this, new PullToRefresh(scroll,
                () -> foreground && scan.isEnabled(),
                () -> run(() -> {
                    JSONObject gate = heartbeat(data);
                    if (!gate.getString("scope_id").equals(data.optString("scope"))) {
                        return "Gate identity changed. Verify the connection settings.";
                    }
                    return "Gate connected · #" + data.optInt("device");
                })));
        feedback = new QrVoiceFeedback(this);
        vault = new Vault(this);
        try {
            data = new JSONObject(vault.read());
            status.setText(data.has("pending") ? "A scan is pending. Retry to confirm its result."
                    : data.has("device") ? "Gate saved · #" + data.optInt("device") : "Connect a registered school gate.");
        } catch (Exception error) {
            status.setText("Protected gate storage could not be opened.");
        }
        buttons();
        opening.awaitReady(EndpointPolicy.BASE, () -> { opening.dismiss(); openingComplete(); }, this::openingComplete);
    }

    @Override protected void onResume() {
        super.onResume();
        foreground = true;
        if (pendingAnnouncement != null) {
            announce(pendingAnnouncement);
            pendingAnnouncement = null;
        }
        if (opened) updates.resume();
    }

    private void openingComplete() { opened = true; if (foreground) updates.resume(); }

    @Override protected void onPause() {
        foreground = false;
        if (feedback != null) feedback.stop();
        updates.pause();
        super.onPause();
    }

    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }

    private Button button(LinearLayout layout, String label, Runnable action) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setOnClickListener(view -> action.run());
        layout.addView(button, new LinearLayout.LayoutParams(-1, -2));
        return button;
    }

    private void buttons() {
        boolean idle = data != null && !busy && scanningDirection == null;
        scan.setEnabled(idle && data.has("device") && !data.has("pending"));
        retry.setEnabled(idle && data.has("pending"));
        connect.setEnabled(idle);
    }

    private void openScanner() {
        scanningDirection = direction.getSelectedItemPosition() == 0 ? "in" : "out";
        buttons();
        new IntentIntegrator(this).setCaptureActivity(QrCaptureActivity.class)
                .setDesiredBarcodeFormats(IntentIntegrator.QR_CODE).setOrientationLocked(true).setBeepEnabled(false)
                .setPrompt(getString(R.string.qr_scan_prompt)).initiateScan();
    }

    private void unlock() {
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        if (keyguard == null || !keyguard.isDeviceSecure()) {
            status.setText("Set a screen lock before changing the gate connection.");
            return;
        }
        Intent unlock = keyguard.createConfirmDeviceCredentialIntent(getString(R.string.app_name), "Unlock to change gate settings.");
        if (unlock != null) startActivityForResult(unlock, UNLOCK);
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString("direction", scanningDirection);
    }

    @Override protected void onActivityResult(int request, int result, Intent intent) {
        super.onActivityResult(request, result, intent);
        if (request == UNLOCK) {
            if (result == RESULT_OK && data != null && !busy) connectionDialog();
            return;
        }
        IntentResult scanResult = IntentIntegrator.parseActivityResult(request, result, intent);
        if (scanResult == null) return;
        String mark = scanningDirection;
        scanningDirection = null;
        buttons();
        String token = scanResult.getContents();
        if (token == null || mark == null || data == null) return;
        if (!token.matches(QR)) { status.setText("Use a InstituteAxis student or staff QR card."); return; }
        run(() -> {
            JSONObject event = new JSONObject().put("event_id", UUID.randomUUID().toString())
                    .put("qr_token", token).put("direction", mark).put("occurred_at", Instant.now().toString());
            store(new JSONObject(data.toString()).put("pending", event));
            return deliver();
        });
    }

    private void connectionDialog() {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), 0, dp(20), 0);
        EditText device = field(form, "Gate ID", InputType.TYPE_CLASS_NUMBER);
        if (data.has("device")) device.setText(data.optString("device"));
        EditText key = field(form, "Connection key", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Connect " + BuildConfig.INSTITUTE_CODE)
                .setView(form).setNegativeButton("Cancel", null).setPositiveButton("Connect", null).create();
        dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String id = device.getText().toString().trim();
            String token = key.getText().toString().trim();
            if (!id.matches("[1-9][0-9]{0,8}") || !token.matches(KEY)) {
                key.setError("Enter the registered Gate ID and connection key.");
                return;
            }
            boolean sameGate = id.equals(data.optString("device"));
            if (data.has("pending") && !sameGate) {
                key.setError("Resolve the pending scan before changing gates.");
                return;
            }
            dialog.dismiss();
            run(() -> {
                JSONObject replacement = new JSONObject(data.toString()).put("device", id).put("key", token);
                if (!sameGate) replacement.remove("scope");
                JSONObject checked = heartbeat(replacement);
                if (replacement.has("pending") && !checked.getString("scope_id").equals(replacement.optString("scope"))) {
                    return "The gate identity has changed. Check recent scans before reconnecting.";
                }
                store(replacement.put("scope", checked.getString("scope_id")));
                return "Gate connected · #" + id;
            });
        });
    }

    private EditText field(LinearLayout form, String hint, int type) {
        EditText field = new EditText(this);
        field.setHint(hint);
        field.setInputType(type);
        field.setSaveEnabled(false);
        field.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        PasswordVisibility.addField(form, field, Color.rgb(20,92,70));
        return field;
    }

    private String deliver() throws Exception {
        JSONObject event = data.getJSONObject("pending");
        JSONObject gate = heartbeat(data);
        if (!gate.getString("scope_id").equals(data.optString("scope"))) return "Gate identity changed. Pending scan retained.";
        String marks = gate.getString("marks");
        if (!"both".equals(marks) && !event.getString("direction").equals(marks)) {
            JSONObject state = new JSONObject(data.toString());
            state.remove("pending");
            store(state);
            return "This gate does not allow that direction. Choose IN or OUT and scan again.";
        }
        long age = java.time.Duration.between(Instant.parse(event.getString("occurred_at")), Instant.now()).getSeconds();
        if (age < -60 || age > 840) {
            JSONObject state = new JSONObject(data.toString());
            state.remove("pending");
            store(state);
            return "Scan expired. Check scan history before taking attendance again.";
        }
        Reply reply = post(data, "events", event);
        if (reply.code == 200 || reply.code == 201 || reply.code == 409 || reply.code == 422) {
            JSONObject state = new JSONObject(data.toString());
            state.remove("pending");
            store(state);
            if (reply.code == 200 || reply.code == 201) {
                String outcome = reply.body.getString("outcome");
                if (QrVoicePolicy.shouldAnnounce(outcome)) {
                    savedScanAnnouncement = new Announcement(reply.body.optString("person_name", ""),
                            "Already marked".equals(outcome));
                }
                return outcome + ": " + reply.body.optString("reason");
            }
            return "Scan refused (" + reply.code + "). Check attendance history.";
        }
        return "Scan not confirmed. Retry uses the same submission.";
    }

    private JSONObject heartbeat(JSONObject connection) throws Exception {
        Reply reply = post(connection, "heartbeat", new JSONObject().put("model", android.os.Build.MODEL)
                .put("client_version", BuildConfig.VERSION_NAME));
        if (reply.code != 200 || !reply.body.optString("scope_id").matches("[a-f0-9]{64}")) {
            throw new IllegalStateException("Gate verification failed. Check the ID, key and network.");
        }
        String state = reply.body.getString("status");
        if (!"Approved".equals(state) && !"Pending".equals(state)) throw new IllegalStateException("This gate is paused.");
        Instant server = OffsetDateTime.parse(reply.body.getString("server_time")).toInstant();
        if (Math.abs(java.time.Duration.between(Instant.now(), server).getSeconds()) > 60) {
            throw new IllegalStateException("Set automatic date and time on this phone, then retry.");
        }
        return reply.body;
    }

    private record Reply(int code, JSONObject body) {}

    private Reply post(JSONObject config, String path, JSONObject body) throws Exception {
        String id = config.getString("device"), token = config.getString("key");
        if (!id.matches("[1-9][0-9]{0,8}") || !token.matches(KEY) || BuildConfig.INSTITUTE_CODE.isEmpty()) {
            throw new IllegalStateException("Get the QR Attendance APK from your school’s App Links.");
        }
        HttpsURLConnection connection = (HttpsURLConnection) new URL(EndpointPolicy.BASE
                + "/api/attendance/devices/" + id + "/" + path).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(10_000);
        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("X-Institute-Code", BuildConfig.INSTITUTE_CODE);
        if ("events".equals(path)) connection.setRequestProperty("X-Device-Scope", config.getString("scope"));
        try {
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
            int code = connection.getResponseCode();
            if (code >= 300) return new Reply(code, new JSONObject());
            try (InputStream input = connection.getInputStream()) {
                ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                byte[] block = new byte[1024];
                for (int count; (count = input.read(block)) != -1;) {
                    if (buffer.size() + count > 16_384) throw new IllegalStateException("Gate reply too large.");
                    buffer.write(block, 0, count);
                }
                return new Reply(code, new JSONObject(buffer.toString(StandardCharsets.UTF_8.name())));
            }
        } finally { connection.disconnect(); }
    }

    private void store(JSONObject next) throws Exception {
        vault.save(next.toString());
        data = next;
    }

    private void announce(Announcement announcement) {
        feedback.confirm(announcement.name(), false, announcement.alreadyMarked());
    }

    private interface Work { String execute() throws Exception; }

    private void run(Work work) {
        if (busy) return;
        busy = true;
        status.setText("Connecting to the school gate…");
        buttons();
        worker.execute(() -> {
            String message;
            savedScanAnnouncement = null;
            try { message = work.execute(); }
            catch (IllegalStateException error) { message = error.getMessage(); }
            catch (Exception error) { message = "Could not confirm the request. Check the connection and retry any pending scan."; }
            String result = message;
            Announcement confirmed = savedScanAnnouncement;
            runOnUiThread(() -> {
                if (isDestroyed()) return;
                busy = false;
                status.setText(confirmed != null && !confirmed.name().isEmpty() ? confirmed.name() + "\n" + result : result);
                buttons();
                // The scanner activity can return a result before onResume.
                // Retain one confirmed announcement until the activity is visible.
                if (confirmed != null && feedback != null) {
                    if (foreground) announce(confirmed);
                    else pendingAnnouncement = confirmed;
                }
            });
        });
    }

    @Override protected void onDestroy() {
        opening.close();
        worker.shutdown();
        if (feedback != null) feedback.close();
        super.onDestroy();
    }
}
