package com.schoolflow.clients;

import com.schoolflow.mobile.ReadinessPolicy;
import org.junit.Test;
import static org.junit.Assert.*;

public class ReadinessPolicyTest {
    @Test public void acceptsOnlyVerifiedSchoolHealth() {
        assertTrue(ReadinessPolicy.health(200, "application/json; charset=utf-8", "1", "ok", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(200, "text/html", "1", "ok", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(200, "text/html", null, "", ""));
        assertFalse(ReadinessPolicy.health(503, "application/json", "1", "ok", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(302, "application/json", "1", "ok", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(200, "application/json", null, "ok", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(200, "application/json", "1", "waiting", "schoolflow-system-audit-v38"));
        assertFalse(ReadinessPolicy.health(200, "application/json", "1", "ok", "provider-wakeup"));
        assertFalse(ReadinessPolicy.health(200, null, "1", "ok", null));
    }

    @Test public void renderWakeupAndUnknownDocumentsRemainCovered() {
        assertTrue(ReadinessPolicy.document("\"schoolflow\""));
        assertTrue(ReadinessPolicy.document("\"schoolflow-error\""));
        assertFalse(ReadinessPolicy.document("\"unverified\""));
        assertFalse(ReadinessPolicy.document("\"schoolflow-opening\""));
        assertFalse(ReadinessPolicy.document("null"));
        assertFalse(ReadinessPolicy.document(null));
        assertFalse(ReadinessPolicy.document("\"Application loading\""));
    }
}
