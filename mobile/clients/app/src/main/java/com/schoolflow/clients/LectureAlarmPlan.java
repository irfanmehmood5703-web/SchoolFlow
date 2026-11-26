package com.schoolflow.clients;

import java.util.*;

/** Clock-only logic for the teacher's locally synced lecture alarms. */
final class LectureAlarmPlan {
 static final long MINUTE=60000L, HORIZON=48*60*MINUTE, LATE=5*MINUTE;
 static final class Alert {
  final String id,title,body;
  final long due,start;
  Alert(String id,String title,String body,long due,long start){this.id=id;this.title=title;this.body=body;this.due=due;this.start=start;}
  boolean valid(long now){return id.matches("[a-f0-9]{64}")&&due>0&&start>=due&&start-due<=30*MINUTE&&start>=now-LATE&&due<=now+HORIZON;}
  boolean due(long now){return due<=now&&start>=now-LATE;}
 }
 static List<Alert> ready(List<Alert> alerts,Set<String> fired,long now){
  List<Alert> result=new ArrayList<>();
  for(Alert a:alerts)if(a.valid(now)&&a.due(now)&&!fired.contains(a.id))result.add(a);
  result.sort(Comparator.comparingLong(a->a.due));return result;
 }
 static long next(List<Alert> alerts,Set<String> fired,long now){
  long next=Long.MAX_VALUE;
  for(Alert a:alerts)if(a.valid(now)&&!fired.contains(a.id))next=Math.min(next,Math.max(now+1000L,a.due));
  return next==Long.MAX_VALUE?0:next;
 }
 private LectureAlarmPlan(){}
}
