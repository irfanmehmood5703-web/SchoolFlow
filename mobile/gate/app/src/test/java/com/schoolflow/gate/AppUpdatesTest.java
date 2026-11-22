package com.schoolflow.gate;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import org.junit.Test;

public class AppUpdatesTest {
    @Test public void acceptsOnlyTheOfficialApkForTheOfferedVersion() {
        String url = "https://github.com/irfanmehmood5703-web/SchoolFlow/releases/download/"
                + "qr-attendance-7-123-1/SchoolFlow-QR-Attendance.apk";
        assertTrue(AppUpdates.validLink(url, 7));
        assertFalse(AppUpdates.validLink(url, 8));
        assertFalse(AppUpdates.validLink(url.replace("github.com", "github.com.example.org"), 7));
        assertFalse(AppUpdates.validLink(url + "?redirect=1", 7));
    }
}
