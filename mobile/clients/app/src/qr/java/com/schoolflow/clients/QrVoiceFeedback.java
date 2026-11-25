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
    private static final String MESSAGE = "Thank you. Attendance marked.";
    private final Handler main = new Handler(Looper.getMainLooper());
    private TextToSpeech speech;
    private ToneGenerator tone;
    private boolean ready, closed;

    QrVoiceFeedback(Context context) {
        try {
            speech = new TextToSpeech(context.getApplicationContext(),
                    result -> main.post(() -> initialize(result)));
        } catch (RuntimeException ignored) {
            // No text-to-speech engine installed. Use a short confirmation tone.
        }
    }

    private void initialize(int result) {
        if (closed || speech == null || result != TextToSpeech.SUCCESS) return;
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
        } catch (RuntimeException ignored) { ready = false; }
    }

    // Android has no standard voice-gender property. Prefer explicitly
    // female-named offline voices, otherwise use the available local voice.
    private static int rank(Voice voice) {
        if (voice == null) return -1;
        String name = voice.getName().toLowerCase(Locale.ROOT);
        int female = name.contains("female") || name.contains("woman") ? 100 : 0;
        return female + ("US".equals(voice.getLocale().getCountry()) ? 10 : 0);
    }

    void confirm() {
        if (closed) return;
        try {
            if (ready && speech != null && speech.speak(MESSAGE, TextToSpeech.QUEUE_FLUSH,
                    null, "attendance-confirmed") == TextToSpeech.SUCCESS) return;
        } catch (RuntimeException ignored) { /* use confirmation tone */ }
        try {
            if (tone == null) tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 35);
            tone.startTone(ToneGenerator.TONE_PROP_ACK, 180);
        } catch (RuntimeException ignored) { /* audio may be unavailable */ }
    }

    void stop() {
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
