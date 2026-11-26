package com.schoolflow.clients;
import org.junit.Test;
import java.util.Collections;
import static org.junit.Assert.*;

public class QrVoicePolicyTest {
    @Test public void acceptsInstalledEnglishOnly() {
        assertTrue(QrVoicePolicy.usable("en",false,Collections.emptySet()));
        assertFalse(QrVoicePolicy.usable("en",true,Collections.emptySet()));
        assertFalse(QrVoicePolicy.usable("en",false,Collections.singleton("notInstalled")));
        assertFalse(QrVoicePolicy.usable("ur",false,Collections.emptySet()));
        assertTrue(QrVoicePolicy.rank("UK female","GB") > QrVoicePolicy.rank("default","US"));
    }
    @Test public void announcesStudentNotSchoolName() {
        assertEquals("Imran Ali. Attendance marked. Thank you.", QrVoicePolicy.message("Imran Ali"));
        assertEquals("Attendance marked. Thank you.", QrVoicePolicy.message(""));
        assertEquals("Imran Ali. Attendance marked. Thank you.", QrVoicePolicy.message("Imran\nAli"));
    }
    @Test public void announcesAlreadyMarkedSeparatelyFromNewAttendance() {
        assertTrue(QrVoicePolicy.shouldAnnounce("Marked"));
        assertTrue(QrVoicePolicy.shouldAnnounce("Already marked"));
        assertFalse(QrVoicePolicy.shouldAnnounce("Not marked"));
        assertFalse(QrVoicePolicy.shouldAnnounce(null));
        assertEquals("Imran Ali. Your attendance is already marked.", QrVoicePolicy.message("Imran Ali", true));
        assertEquals("Your attendance is already marked.", QrVoicePolicy.message("", true));
    }
}
