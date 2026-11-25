package com.schoolflow.clients;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import android.os.Handler;
import android.os.Looper;
import java.util.Locale;
import java.util.Set;

/** Local audible confirmation, without transmitting student names or QR data. */
final class QrVoiceFeedback {
    private String waitingMessage;
    private boolean initializing = true;
    private int generation;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Context speechContext;
    private TextToSpeech speech;
    private ToneGenerator tone;
    private boolean ready, closed;

    QrVoiceFeedback(Context context) {
        speechContext = context.getApplicationContext();
        try {
            speech = new TextToSpeech(context.getApplicationContext(),
                    result -> main.post(() -> initialize(result)));
        } catch (RuntimeException ignored) {
            initializing = false; // No engine installed; confirmation tone remains available.
        }
    }

    private void initialize(int result) {
        initializing = false;
        if (closed || speech == null || result != TextToSpeech.SUCCESS) { waitingMessage = null; return; }
        try {
            if (speech.setLanguage(Locale.US) < TextToSpeech.LANG_AVAILABLE) return;
            Set<Voice> voices = speech.getVoices();
            Voice current = speech.getVoice();
            Voice chosen = current != null && !current.isNetworkConnectionRequired()
                    && "en".equals(current.getLocale().getLanguage()) ? current : null;
            int rank = rank(chosen);
            if (voices != null) for (Voice voice : voices) {
                if (voice.isNetworkConnectionRequired() || !"en".equals(voice.getLocale().getLanguage())) continue;
                int score = rank(voice);
                if (score > rank) { chosen = voice; rank = score; }
            }
            if (chosen == null || speech.setVoice(chosen) != TextToSpeech.SUCCESS) return;
            speech.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            speech.setSpeechRate(0.95f);
            ready = true;
            if (waitingMessage != null) { String message = waitingMessage; waitingMessage = null; speak(message); }
        } catch (RuntimeException ignored) { ready = false; } finally { if (!ready) waitingMessage = null; }
    }

    // Android has no standard voice-gender property. Prefer explicitly
    // female-named offline voices, otherwise use the available local voice.
    private static int rank(Voice voice) {
        if (voice == null) return -1;
        String name = voice.getName().toLowerCase(Locale.ROOT);
        int female = name.contains("female") || name.contains("woman") ? 100 : 0;
        return female + ("US".equals(voice.getLocale().getCountry()) ? 10 : 0);
    }

    void confirm(String name, boolean test) {
        if (closed) return;
        String safe = name == null ? "" : name.replaceAll("[\\p{Cntrl}]", " ").trim();
        if (safe.length() > 100) safe = safe.substring(0, 100);
        String message = (safe.isEmpty() ? "" : safe + ". ") + "Thank you. Attendance marked.";
        // A short audible acknowledgement is always attempted, even when
        // TTS claims success but the installed voice cannot actually play.
        int ticket = ++generation;
        try {
            if (tone == null) tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 80);
            tone.startTone(ToneGenerator.TONE_PROP_ACK, 140);
        } catch (RuntimeException ignored) { /* media stream may be unavailable */ }
        main.postDelayed(() -> {
            if (closed || ticket != generation) return;
            if (ready) speak(message);
            else if (initializing) {
                waitingMessage = message;
                main.postDelayed(() -> { if (ticket == generation) waitingMessage = null; }, 2500);
            }
        }, 180);
        if (test && !ready && !initializing) {
            android.widget.Toast.makeText(speechContext, "Offline English voice unavailable. Check Android text-to-speech settings.", android.widget.Toast.LENGTH_LONG).show();
        }
    }

    private void speak(String message) {
        try {
            if (ready && speech != null) speech.speak(message, TextToSpeech.QUEUE_FLUSH, null, "attendance-confirmed");
        } catch (RuntimeException ignored) { /* acknowledgement tone has already played */ }
    }

    void stop() {
        generation++; waitingMessage = null;
        if (speech != null) speech.stop();
        if (tone != null) tone.stopTone();
    }

    void close() {
        closed = true;
        main.removeCallbacksAndMessages(null);
        stop();
        if (speech != null) { speech.shutdown(); speech = null; }
        if (tone != null) { tone.release(); tone = null; }
    }
}
