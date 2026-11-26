package com.schoolflow.clients;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Local audible confirmation. Student names are never sent to network voices. */
final class QrVoiceFeedback {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Context speechContext;
    private TextToSpeech speech;
    private ToneGenerator tone;
    private final List<Voice> voices = new ArrayList<>();
    private int generation, engineGeneration, attempt, voiceIndex;
    private boolean initializing, closed, speaking, testRequest;
    private String waitingMessage;
    private String activeUtterance;

    QrVoiceFeedback(Context context) {
        speechContext = context.getApplicationContext();
        openEngine();
    }

    private void openEngine() {
        if (closed || initializing) return;
        if (speech != null) { speech.shutdown(); speech = null; }
        voices.clear();
        initializing = true;
        int engine = ++engineGeneration;
        try {
            speech = new TextToSpeech(speechContext,
                    result -> main.post(() -> initialize(engine, result)));
            main.postDelayed(() -> {
                if (engine == engineGeneration && initializing) {
                    initializing = false;
                    unavailable();
                }
            }, 8000);
        } catch (RuntimeException ignored) {
            initializing = false;
            unavailable();
        }
    }

    private void initialize(int engine, int result) {
        if (closed || engine != engineGeneration) return;
        initializing = false;
        if (speech == null || result != TextToSpeech.SUCCESS) { unavailable(); return; }
        try {
            // Do not require US English: an installed UK or other English
            // offline voice is equally usable. Never choose missing voice data.
            Voice current = speech.getVoice();
            Set<Voice> available = speech.getVoices();
            if (available != null) for (Voice voice : available) {
                if (usable(voice)) voices.add(voice);
            }
            if (usable(current) && !voices.contains(current)) voices.add(current);
            voices.sort(Comparator.comparingInt(QrVoiceFeedback::rank).reversed());
            speech.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            speech.setSpeechRate(0.95f);
            speech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String id) {
                    main.post(() -> {
                        if (id.equals(activeUtterance)) speaking = true;
                    });
                }
                @Override public void onDone(String id) {
                    main.post(() -> {
                        if (id.equals(activeUtterance)) {
                            activeUtterance = null; waitingMessage = null; speaking = false;
                        }
                    });
                }
                @Override public void onError(String id) { fail(id); }
                @Override public void onError(String id, int code) { fail(id); }
                private void fail(String id) {
                    main.post(() -> {
                        if (id.equals(activeUtterance)) retryVoice();
                    });
                }
            });
            if (waitingMessage != null) playNext();
        } catch (RuntimeException ignored) {
            voices.clear();
            unavailable();
        }
    }

    private static boolean usable(Voice voice) {
        return voice != null && QrVoicePolicy.usable(voice.getLocale().getLanguage(),
                voice.isNetworkConnectionRequired(), voice.getFeatures());
    }

    private static int rank(Voice voice) {
        return QrVoicePolicy.rank(voice.getName(), voice.getLocale().getCountry());
    }

    void confirm(String name, boolean test) {
        if (closed) return;
        stop();
        waitingMessage = QrVoicePolicy.message(name);
        testRequest = test;
        attempt = 0;
        voiceIndex = 0;
        int ticket = generation;
        try {
            if (tone == null) tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 80);
            tone.startTone(ToneGenerator.TONE_PROP_ACK, 140);
        } catch (RuntimeException ignored) { /* speech may still work */ }
        main.postDelayed(() -> {
            if (closed || ticket != generation || waitingMessage == null) return;
            if (initializing) return;
            if (voices.isEmpty()) openEngine(); // Recover after a temporary engine failure.
            else playNext();
        }, 180);
    }

    private void playNext() {
        if (closed || waitingMessage == null || initializing) return;
        if (speech == null) { unavailable(); return; }
        while (voiceIndex < voices.size()) {
            Voice voice = voices.get(voiceIndex++);
            String id = "attendance-" + generation + "-" + (++attempt);
            try {
                if (speech.setVoice(voice) != TextToSpeech.SUCCESS) continue;
                // Some engines silently substitute their default voice.
                // Check again before providing any student's name.
                if (!usable(speech.getVoice())) continue;
                activeUtterance = id;
                speaking = false;
                if (speech.speak(waitingMessage, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) {
                    activeUtterance = null;
                    continue;
                }
                main.postDelayed(() -> {
                    if (id.equals(activeUtterance) && !speaking) retryVoice();
                }, 4500);
                // Clear a stalled utterance even if an engine never sends onDone.
                main.postDelayed(() -> {
                    if (id.equals(activeUtterance)) {
                        if (!speaking) retryVoice();
                        else { activeUtterance = null; waitingMessage = null; speaking = false; }
                    }
                }, 20000);
                return;
            } catch (RuntimeException ignored) { activeUtterance = null; }
        }
        unavailable();
    }

    private void retryVoice() {
        activeUtterance = null;
        speaking = false;
        try { if (speech != null) speech.stop(); } catch (RuntimeException ignored) {}
        playNext();
    }

    private void unavailable() {
        if (waitingMessage == null) return;
        waitingMessage = null;
        activeUtterance = null;
        speaking = false;
        if (testRequest && !closed) Toast.makeText(speechContext,
                "Speech unavailable. Install or enable an offline English text-to-speech voice, then test again.",
                Toast.LENGTH_LONG).show();
    }

    void stop() {
        generation++; waitingMessage = null; activeUtterance = null; speaking = false;
        try { if (speech != null) speech.stop(); } catch (RuntimeException ignored) {}
        if (tone != null) tone.stopTone();
    }

    void close() {
        closed = true;
        engineGeneration++;
        main.removeCallbacksAndMessages(null);
        stop();
        if (speech != null) { speech.shutdown(); speech = null; }
        if (tone != null) { tone.release(); tone = null; }
    }
}
