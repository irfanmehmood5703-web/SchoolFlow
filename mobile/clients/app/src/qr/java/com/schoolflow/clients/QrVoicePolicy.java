package com.schoolflow.clients;

import java.util.Locale;
import java.util.Set;

final class QrVoicePolicy {
    static boolean usable(String language, boolean network, Set<String> features) {
        return "en".equals(language) && !network
                && (features == null || !features.contains("notInstalled"));
    }

    static int rank(String name, String country) {
        String value = name.toLowerCase(Locale.ROOT);
        int female = value.contains("female") || value.contains("woman") ? 100 : 0;
        return female + ("US".equals(country) ? 10 : 0);
    }

    static boolean shouldAnnounce(String outcome) {
        return "Marked".equals(outcome) || "Already marked".equals(outcome);
    }

    static String message(String name) {
        return message(name, false);
    }

    static String message(String name, boolean alreadyMarked) {
        String safe = name == null ? "" : name.replaceAll("[\\p{Cntrl}]", " ").trim();
        if (safe.length() > 100) safe = safe.substring(0, 100);
        return (safe.isEmpty() ? "" : safe + ". ") + (alreadyMarked
                ? "Your attendance is already marked." : "Attendance marked. Thank you.");
    }
}
