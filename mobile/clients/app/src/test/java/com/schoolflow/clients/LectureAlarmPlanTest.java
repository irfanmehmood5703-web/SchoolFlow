package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
import java.util.*;

public class LectureAlarmPlanTest {
 private final long now=1760000000000L;
 private LectureAlarmPlan.Alert a(String digit,long due,long start){return new LectureAlarmPlan.Alert(digit.repeat(64),"Lecture","Math · 11:30 AM",due,start);}
 @Test public void selectsNextAndDeliversOnlyInWindow(){
  LectureAlarmPlan.Alert upcoming=a("a",now+5*60000,now+10*60000),due=a("b",now-1000,now+4*60000);
  LectureAlarmPlan.Alert expired=a("c",now-20*60000,now-10*60000),invalid=a("d",now,now-1);
  List<LectureAlarmPlan.Alert> rows=Arrays.asList(upcoming,due,expired,invalid);
  Set<String> fired=new HashSet<>();
  assertEquals(Collections.singletonList(due),LectureAlarmPlan.ready(rows,fired,now));
  assertEquals(now+1000,LectureAlarmPlan.next(rows,fired,now));
  fired.add(due.id);
  assertTrue(LectureAlarmPlan.ready(rows,fired,now).isEmpty());
  assertEquals(upcoming.due,LectureAlarmPlan.next(rows,fired,now));
  fired.add(upcoming.id);
  assertEquals(0,LectureAlarmPlan.next(rows,fired,now));
 }
 @Test public void acceptsDelayedAlarmWithinFiveMinutesAndRejectsStaleFuture(){
  LectureAlarmPlan.Alert late=a("e",now-60000*6,now-60000);
  assertTrue(late.valid(now));assertTrue(late.due(now));
  assertFalse(late.valid(now+60000*5));
  assertFalse(a("f",now+LectureAlarmPlan.HORIZON+1,now+LectureAlarmPlan.HORIZON+60000).valid(now));
 }
}
