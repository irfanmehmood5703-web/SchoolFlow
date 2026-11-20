package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
public class SmsRunTest {
 @Test public void defaultsToTwentyAndAcceptsOnlySupportedIntervals(){assertEquals(20,SmsRun.DEFAULT_INTERVAL);for(int n:new int[]{15,20,25})assertTrue(SmsRun.validInterval(n));for(int n:new int[]{0,1,14,19,30,-1})assertFalse(SmsRun.validInterval(n));}
 @Test public void spacesMessagesForEveryInterval(){for(int seconds:new int[]{15,20,25}){SmsRun run=new SmsRun();run.start(seconds);assertTrue(run.ready(1000));run.dispatched(1000);assertFalse(run.ready(1000+seconds*1000L-1));assertTrue(run.ready(1000+seconds*1000L));}}
 @Test public void pauseAndUncertaintyNeverResumeOrResetSpacing(){SmsRun run=new SmsRun();run.start(20);run.dispatched(1000);run.stop();assertFalse(run.ready(999999));run.start(15);assertFalse(run.ready(10000));assertTrue(run.ready(21000));run.uncertain();assertFalse(run.ready(999999));}
 @Test public void serverDelayCanExtendButCannotShortenTheTimer(){SmsRun run=new SmsRun();run.start(20);run.dispatched(1000);run.serverWait(2000,1);assertEquals(19000,run.delay(2000));run.serverWait(2000,25);assertEquals(25000,run.delay(2000));}
 @Test(expected=IllegalArgumentException.class) public void invalidIntervalCannotStartARun(){new SmsRun().start(1);}
}
