package com.schoolflow.gate;
import org.junit.Test;
import static org.junit.Assert.*;
public class EndpointBuildTest {
 @Test public void variantsHaveSeparateTrustedTargets(){String expected="debug".equals(BuildConfig.BUILD_TYPE)?"https://schoolflow-gate-trial-irfan.onrender.com":"https://schoolflow-phase1.onrender.com";assertEquals(expected,EndpointPolicy.BASE);EndpointPolicy.validate(expected,"FICTIONAL-QA",1,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");}
 @Test(expected=IllegalArgumentException.class)public void anotherTargetCannotReplaceCompiledHost(){EndpointPolicy.validate("https://evil.invalid","FICTIONAL-QA",1,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");}
}
