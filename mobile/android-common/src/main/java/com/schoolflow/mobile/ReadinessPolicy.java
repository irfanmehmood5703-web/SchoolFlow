package com.schoolflow.mobile;

import java.util.Locale;

/** A successful HTTP response alone is not evidence that the school is ready. */
public final class ReadinessPolicy {
    public static final long WAIT_MS = 105_000;
    public static final long RETRY_MS = 2_500;
    public static final int REQUEST_MS = 12_000;
    private ReadinessPolicy() {}

    public static boolean health(int code, String mime, String marker, String status, String build) {
        return code == 200 && mime != null
                && mime.toLowerCase(Locale.ROOT).split(";", 2)[0].trim().equals("application/json")
                && "1".equals(marker) && "ok".equals(status)
                && build != null && build.startsWith("schoolflow-");
    }

    /** Keep document errors visible, but never treat an unmarked hosting page as the app. */
    public static boolean document(String result) {
        return "\"schoolflow\"".equals(result) || "\"schoolflow-error\"".equals(result);
    }
}
