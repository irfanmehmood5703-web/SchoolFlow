package com.schoolflow.clients;

import android.content.Context;
import android.content.Intent;
import android.content.pm.ResolveInfo;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.ToneGenerator;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.function.Consumer;

/** Generate and play speech locally; never send names to network voices. Main-thread state. */
final class QrVoiceFeedback {
    private static final AudioAttributes AUDIO = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Context context;
    private final Consumer<String> status;
    private final List<String> engines = new ArrayList<>();
    private final List<Voice> voices = new ArrayList<>();
    private TextToSpeech speech;
    private ToneGenerator tone;
    private MediaPlayer player;
    private File audioFile;
    private int generation, engineGeneration, attempt, engineIndex, voiceIndex;
    private boolean initializing, closed, started, direct;
    private String message, activeId;
    private Voice selected;

    QrVoiceFeedback(Context context, Consumer<String> status) {
        this.context = context.getApplicationContext();
        this.status = status;
        // Remove orphaned private audio from a previous interrupted process.
        File[] stale = this.context.getCacheDir().listFiles((dir, name) -> name.startsWith("qr-voice-") && name.endsWith(".wav"));
        if (stale != null) for (File file : stale) file.delete();
    }

    private void collectEngines() {
        engines.clear();
        engines.add(null); // System preferred engine first.
        try {
            for (ResolveInfo info : context.getPackageManager().queryIntentServices(
                    new Intent(TextToSpeech.Engine.INTENT_ACTION_TTS_SERVICE), 0)) {
                if (info.serviceInfo != null && !engines.contains(info.serviceInfo.packageName))
                    engines.add(info.serviceInfo.packageName);
            }
        } catch (RuntimeException ignored) {}
        engineIndex = 0;
    }

    private void openNextEngine() {
        if (closed || message == null) return;
        resetEngine();
        if (engineIndex >= engines.size()) {
            unavailable("No working offline English voice. Install English voice data in Voice settings.");
            return;
        }
        initializing = true;
        int token = engineGeneration;
        String engine = engines.get(engineIndex++);
        try {
            TextToSpeech.OnInitListener listener = result -> main.post(() -> initialize(token, result));
            speech = engine == null ? new TextToSpeech(context, listener)
                    : new TextToSpeech(context, listener, engine);
            main.postDelayed(() -> {
                if (!closed && token == engineGeneration && initializing) openNextEngine();
            }, 6000);
        } catch (RuntimeException ignored) {
            openNextEngine();
        }
    }

    private void initialize(int token, int result) {
        if (closed || token != engineGeneration || !initializing) return;
        initializing = false;
        if (speech == null || result != TextToSpeech.SUCCESS) { openNextEngine(); return; }
        try {
            // Older engines sometimes expose no usable current voice until
            // an explicit language selection, so prime English and query again.
            collectVoices();
            if (voices.isEmpty()) {
                for (Locale locale : new Locale[]{Locale.US, Locale.UK, Locale.ENGLISH}) {
                    if (speech.setLanguage(locale) >= TextToSpeech.LANG_AVAILABLE) collectVoices();
                    if (!voices.isEmpty()) break;
                }
            }
            if (voices.isEmpty()) { openNextEngine(); return; }
            speech.setAudioAttributes(AUDIO);
            speech.setSpeechRate(0.95f);
            speech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String id) {
                    main.post(() -> { if (matches(id)) started = true; });
                }
                @Override public void onDone(String id) {
                    main.post(() -> {
                        if (!matches(id)) return;
                        if (direct) complete();
                        else playFile(id);
                    });
                }
                @Override public void onError(String id) { fail(id); }
                @Override public void onError(String id, int code) { fail(id); }
                @Override public void onStop(String id, boolean interrupted) { fail(id); }
                private void fail(String id) {
                    main.post(() -> { if (matches(id)) retry(); });
                }
            });
            voiceIndex = 0;
            if (message != null) nextVoice();
        } catch (RuntimeException ignored) {
            openNextEngine();
        }
    }

    private void collectVoices() {
        Voice current = speech.getVoice();
        Set<Voice> available = speech.getVoices();
        if (available != null) for (Voice voice : available) addVoice(voice);
        addVoice(current);
        voices.sort(Comparator.comparingInt(QrVoiceFeedback::rank).reversed());
    }

    private void addVoice(Voice v) {
        if (usable(v) && !voices.contains(v)) voices.add(v);
    }

    private static boolean usable(Voice voice) {
        return voice != null && voice.getLocale() != null && QrVoicePolicy.usable(
                voice.getLocale().getLanguage(), voice.isNetworkConnectionRequired(), voice.getFeatures());
    }

    private static int rank(Voice voice) {
        return QrVoicePolicy.rank(voice.getName(), voice.getLocale().getCountry());
    }

    void confirm(String name, boolean test, boolean alreadyMarked) {
        if (closed) return;
        stop();
        message = QrVoicePolicy.message(name, alreadyMarked);
        status.accept("Voice: preparing speech...");
        int ticket = generation;
        try {
            if (tone == null) tone = new ToneGenerator(AudioManager.STREAM_MUSIC, 80);
            tone.startTone(ToneGenerator.TONE_PROP_ACK, 140);
        } catch (RuntimeException ignored) {}
        main.postDelayed(() -> {
            if (closed || ticket != generation || message == null) return;
            if (initializing) return;
            if (speech != null && !voices.isEmpty()) {
                voiceIndex = 0;
                nextVoice();
            } else {
                collectEngines();
                openNextEngine();
            }
        }, 250);
        main.postDelayed(() -> {
            if (!closed && ticket == generation && message != null)
                unavailable("Speech timed out. Check Voice settings and try again.");
        }, 30000);
    }

    private boolean matches(String id) {
        return !closed && message != null && id != null && id.equals(activeId);
    }

    private boolean select(Voice voice) {
        try {
            // A voice can change while the app is open; verify the actual
            // selected voice before passing any name to the engine.
            return usable(voice) && speech.setVoice(voice) == TextToSpeech.SUCCESS
                    && usable(speech.getVoice());
        } catch (RuntimeException ignored) { return false; }
    }

    private void nextVoice() {
        if (closed || message == null) return;
        clearAttempt();
        while (voiceIndex < voices.size()) {
            selected = voices.get(voiceIndex++);
            if (select(selected)) { synthesize(); return; }
        }
        openNextEngine();
    }

    private void synthesize() {
        direct = false;
        String id = activeId = "qr-" + generation + "-" + (++attempt);
        try {
            audioFile = File.createTempFile("qr-voice-", ".wav", context.getCacheDir());
            if (speech.synthesizeToFile(message, new Bundle(), audioFile, id) != TextToSpeech.SUCCESS) {
                retry(); return;
            }
            main.postDelayed(() -> { if (matches(id) && player == null) retry(); }, 7000);
        } catch (IOException | RuntimeException ignored) { retry(); }
    }

    private void playFile(String id) {
        if (!matches(id)) return;
        if (audioFile == null || audioFile.length() <= 44) { retry(); return; }
        try {
            MediaPlayer next = new MediaPlayer();
            player = next;
            next.setAudioAttributes(AUDIO);
            next.setDataSource(audioFile.getAbsolutePath());
            next.setOnPreparedListener(p -> {
                if (!matches(id) || player != p) return;
                try {
                    p.start();
                    status.accept("Voice: playing");
                } catch (RuntimeException ignored) { retry(); }
            });
            next.setOnCompletionListener(p -> { if (matches(id) && player == p) complete(); });
            next.setOnErrorListener((p, what, extra) -> {
                if (matches(id) && player == p) retry();
                return true;
            });
            next.prepareAsync();
            main.postDelayed(() -> { if (matches(id)) retry(); }, 15000);
        } catch (IOException | RuntimeException ignored) { retry(); }
    }

    private void speakDirect() {
        if (!select(selected)) { nextVoice(); return; }
        direct = true;
        started = false;
        String id = activeId = "qr-" + generation + "-" + (++attempt);
        Bundle params = new Bundle();
        params.putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, 1.0f);
        params.putInt(TextToSpeech.Engine.KEY_PARAM_STREAM, AudioManager.STREAM_MUSIC);
        try {
            if (speech.speak(message, TextToSpeech.QUEUE_FLUSH, params, id) != TextToSpeech.SUCCESS) {
                nextVoice(); return;
            }
            main.postDelayed(() -> { if (matches(id) && !started) retry(); }, 4500);
            main.postDelayed(() -> { if (matches(id)) retry(); }, 15000);
        } catch (RuntimeException ignored) { nextVoice(); }
    }

    private void retry() {
        if (closed || message == null) return;
        boolean triedDirect = direct;
        clearAttempt();
        // Post continuation to avoid a deep synchronous chain on broken engines.
        int ticket = generation;
        main.post(() -> {
            if (closed || ticket != generation || message == null) return;
            if (!triedDirect) speakDirect();
            else nextVoice();
        });
    }

    private void complete() {
        message = null;
        clearAttempt();
        status.accept("Voice: playback completed");
    }

    private void unavailable(String reason) {
        if (message == null || closed) return;
        stop();
        resetEngine();
        status.accept("Voice: " + reason);
    }

    private void clearAttempt() {
        activeId = null;
        started = false;
        if (player != null) {
            try { player.release(); } catch (RuntimeException ignored) {}
            player = null;
        }
        if (speech != null) try { speech.stop(); } catch (RuntimeException ignored) {}
        if (audioFile != null) { audioFile.delete(); audioFile = null; }
    }

    private void resetEngine() {
        clearAttempt();
        engineGeneration++;
        initializing = false;
        if (speech != null) {
            try { speech.shutdown(); } catch (RuntimeException ignored) {}
            speech = null;
        }
        voices.clear();
        selected = null;
    }

    void stop() {
        generation++;
        message = null;
        clearAttempt();
        if (initializing) resetEngine();
        if (tone != null) tone.stopTone();
    }

    void close() {
        closed = true;
        main.removeCallbacksAndMessages(null);
        stop();
        resetEngine();
        if (tone != null) { tone.release(); tone = null; }
    }
}
