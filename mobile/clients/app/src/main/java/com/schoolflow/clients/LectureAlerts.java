package com.schoolflow.clients;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.webkit.CookieManager;
import org.json.*;
import java.util.*;

/** One pending OS alarm for the next synced lecture; no network is needed at its due time. */
public final class LectureAlerts extends BroadcastReceiver {
 private static final String STATE="teacher_lecture_alerts",CHANNEL="teacher_lecture_reminders";
 private static final String ACTION="com.schoolflow.clients.LECTURE_DUE";
 private static final int ALARM=7314,NOTICE=7315;
 private static boolean teacher(){return "teacher".equals(BuildConfig.ROLE);}
 private static SharedPreferences state(Context c){return c.getSharedPreferences(STATE,Context.MODE_PRIVATE);}
 private static boolean permitted(Context c){
  return (Build.VERSION.SDK_INT<33||c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED)
      &&c.getSystemService(NotificationManager.class).areNotificationsEnabled();
 }
 private static void channel(Context c){
  c.getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel(CHANNEL,"Lecture reminders",NotificationManager.IMPORTANCE_HIGH));
 }
 public static void explainExact(Activity a){
  if(!teacher())return;
  channel(a);
  if(Build.VERSION.SDK_INT<31||!permitted(a)||a.getSystemService(AlarmManager.class).canScheduleExactAlarms())return;
  SharedPreferences prefs=a.getPreferences(Context.MODE_PRIVATE);
  if(prefs.getBoolean("lecture_exact_explained",false))return;
  prefs.edit().putBoolean("lecture_exact_explained",true).apply();
  new AlertDialog.Builder(a).setTitle("On-time lecture reminders")
   .setMessage("Allow Alarms & reminders so your scheduled lecture alerts can appear even when Teacher App is closed. You can change this in Android settings.")
   .setPositiveButton("Open settings",(dialog,which)->{
    try{a.startActivity(new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:"+a.getPackageName())));}
    catch(ActivityNotFoundException|SecurityException ignored){}
   }).setNegativeButton("Not now",null).show();
 }
 private static PendingIntent alarm(Context c){
  return PendingIntent.getBroadcast(c,ALARM,new Intent(c,LectureAlerts.class).setAction(ACTION),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
 }
 private static void cancel(Context c){c.getSystemService(AlarmManager.class).cancel(alarm(c));}
 @android.annotation.SuppressLint("MissingPermission") // Exact permission checked at runtime.
 private static void arm(Context c,long at){
  AlarmManager manager=c.getSystemService(AlarmManager.class);
  PendingIntent pending=alarm(c);
  manager.cancel(pending);
  if(at==0||!permitted(c))return;
  try{
   if(Build.VERSION.SDK_INT<31||manager.canScheduleExactAlarms())manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending);
   else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending);
  }catch(SecurityException e){manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending);}
 }
 public static synchronized void clear(Context c){
  if(!teacher())return;
  cancel(c);state(c).edit().clear().commit();
  c.getSystemService(NotificationManager.class).cancel(NOTICE);
 }
 private static List<LectureAlarmPlan.Alert> parse(JSONArray rows,long now){
  List<LectureAlarmPlan.Alert> result=new ArrayList<>();Set<String> ids=new HashSet<>();
  for(int i=0;i<Math.min(200,rows.length());i++){
   JSONObject row=rows.optJSONObject(i);if(row==null)continue;
   String id=row.optString("id"),title=row.optString("title"),body=row.optString("body");
   LectureAlarmPlan.Alert a=new LectureAlarmPlan.Alert(id,title,body,row.optLong("due_at"),row.optLong("starts_at"));
   if(title.length()>120||body.length()>500||!a.valid(now)||!ids.add(id))continue;
   result.add(a);
  }
  return result;
 }
 private static JSONArray serialized(List<LectureAlarmPlan.Alert> rows)throws JSONException{
  JSONArray result=new JSONArray();
  for(LectureAlarmPlan.Alert a:rows)result.put(new JSONObject().put("id",a.id).put("title",a.title).put("body",a.body).put("due_at",a.due).put("starts_at",a.start));
  return result;
 }
 /** Only an authenticated feed replaces cache; the server's event IDs also deduplicate old polling notices. */
 static synchronized Set<String> sync(Context c,String actor,JSONArray payload,Set<String> priorSeen,long epoch)throws JSONException{
  Set<String> scheduled=new HashSet<>();
  if(!teacher()||epoch!=NoticeJob.sessionEpoch())return scheduled;
  long now=System.currentTimeMillis();
  List<LectureAlarmPlan.Alert> alerts=parse(payload,now);
  SharedPreferences p=state(c);
  boolean same=actor.equals(p.getString("actor",""));
  Set<String> fired=same?new HashSet<>(p.getStringSet("fired",Collections.emptySet())):new HashSet<>();
  if(!same){cancel(c);c.getSystemService(NotificationManager.class).cancel(NOTICE);}
  for(LectureAlarmPlan.Alert a:alerts){
   scheduled.add(a.id);
   if(priorSeen.contains(a.id))fired.add(a.id);
  }
  // Retain deduplication for still-relevant occurrences, including device restarts.
  // Bound storage while retaining all current alerts.
  if(fired.size()>500)fired.retainAll(scheduled);
  p.edit().putString("actor",actor).putString("alerts",serialized(alerts).toString()).putStringSet("fired",fired).putLong("expires",now+LectureAlarmPlan.HORIZON).commit();
  dispatch(c);
  return scheduled;
 }
 /** Fired IDs and the plan live in private, backup-excluded storage. No student data. */
 @android.annotation.SuppressLint("MissingPermission") // Notification permission checked at runtime.
 private static synchronized void dispatch(Context c){
  if(!teacher())return;
  SharedPreferences p=state(c);long now=System.currentTimeMillis();
  if(p.getString("actor","").isEmpty()||p.getLong("expires",0)<now){clear(c);return;}
  if(!permitted(c)){cancel(c);return;}
  try{
   List<LectureAlarmPlan.Alert> alerts=parse(new JSONArray(p.getString("alerts","[]")),now);
   Set<String> fired=new HashSet<>(p.getStringSet("fired",Collections.emptySet()));
   List<LectureAlarmPlan.Alert> due=LectureAlarmPlan.ready(alerts,fired,now);
   if(!due.isEmpty()){
    LectureAlarmPlan.Alert first=due.get(0);
    String body=first.body+(due.size()>1?" · "+(due.size()-1)+" more lecture(s)":"");
    channel(c);
    Intent intent=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
    PendingIntent tap=PendingIntent.getActivity(c,NOTICE,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    Notification publicVersion=new Notification.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Lecture reminder").setContentText("Open your school app").build();
    Notification notice=new Notification.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info)
     .setContentTitle("Lecture reminder").setContentText(body).setStyle(new Notification.BigTextStyle().bigText(body))
     .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion).setContentIntent(tap).setAutoCancel(true).build();
    c.getSystemService(NotificationManager.class).notify(NOTICE,notice);
    for(LectureAlarmPlan.Alert a:due)fired.add(a.id);
    p.edit().putStringSet("fired",fired).commit();
   }
   arm(c,LectureAlarmPlan.next(alerts,fired,now));
  }catch(JSONException|SecurityException e){cancel(c);}
 }
 static void restore(Context c){
  if(!teacher())return;
  try{
   String cookie=CookieManager.getInstance().getCookie(EndpointPolicy.BASE+"/teacher-app/notification-feed");
   if(cookie==null||cookie.isEmpty()){clear(c);return;}
   dispatch(c);
  }catch(RuntimeException ignored){/* A subsequent authenticated sync will restore the plan. */}
 }
 @Override public void onReceive(Context c,Intent intent){
  if(!teacher())return;
  String action=intent.getAction();
  if(ACTION.equals(action)||Intent.ACTION_BOOT_COMPLETED.equals(action)||AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED.equals(action)){
   // A real OS alarm shows the already-synced reminder without opening the app.
   restore(c);
   NoticeJob.schedule(c);
  }
 }
}
