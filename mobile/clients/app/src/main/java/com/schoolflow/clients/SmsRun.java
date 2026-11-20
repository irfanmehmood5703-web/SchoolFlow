package com.schoolflow.clients;
/** Foreground run timing, independent of Android/SIM for deterministic tests. */
final class SmsRun {
 static final int DEFAULT_INTERVAL=20;
 private boolean running;private int interval=DEFAULT_INTERVAL;private long nextAt;
 static boolean validInterval(int seconds){return seconds==15||seconds==20||seconds==25;}
 void start(int seconds){if(!validInterval(seconds))throw new IllegalArgumentException("Invalid SMS interval");interval=seconds;running=true;}
 void stop(){running=false;}
 boolean running(){return running;}
 int interval(){return interval;}
 void dispatched(long monotonicNow){nextAt=Math.max(nextAt,monotonicNow+interval*1000L);}
 void serverWait(long monotonicNow,int seconds){nextAt=Math.max(nextAt,monotonicNow+Math.max(0,seconds)*1000L);}
 long delay(long monotonicNow){return Math.max(0,nextAt-monotonicNow);}
 boolean ready(long monotonicNow){return running&&delay(monotonicNow)==0;}
 void uncertain(){stop();}
}
