package com.schoolflow.clients;

import android.Manifest;
import android.app.*;
import android.app.job.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;
import android.webkit.CookieManager;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** Best-effort OS-scheduled notification checks; no SIM sending or foreground service. */
public final class NoticeJob extends JobService {
 private static final int PERIODIC=7310, ONCE=7311, NOTICE=7312;
 private static final String CHANNEL="school_updates";
 private static final Object LOCK=new Object();
 private final java.util.concurrent.ConcurrentHashMap<Integer,Thread> tasks=new java.util.concurrent.ConcurrentHashMap<>();
 private static final java.util.concurrent.atomic.AtomicLong SESSION_EPOCH=new java.util.concurrent.atomic.AtomicLong();
 public static boolean supported(){return Arrays.asList("owner","parents","teacher","sms").contains(BuildConfig.ROLE);}
 private static boolean permitted(Context c){return Build.VERSION.SDK_INT<33||c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED;}
 public static void setup(Activity a){
  if(!supported())return;
  NotificationManager nm=a.getSystemService(NotificationManager.class);
  nm.createNotificationChannel(new NotificationChannel(CHANNEL,"School updates",NotificationManager.IMPORTANCE_DEFAULT));
  if(!permitted(a)){
   if(!a.getPreferences(Context.MODE_PRIVATE).getBoolean("notice_permission_requested",false)){
    a.getPreferences(Context.MODE_PRIVATE).edit().putBoolean("notice_permission_requested",true).apply();
    a.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},7313);
   }
   return;
  }
  schedule(a);
 }
 public static void schedule(Context c){
  if(!supported()||!permitted(c))return;
  JobScheduler s=c.getSystemService(JobScheduler.class);
  ComponentName name=new ComponentName(c,NoticeJob.class);
  if(s.getPendingJob(PERIODIC)==null)s.schedule(new JobInfo.Builder(PERIODIC,name).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPeriodic(15*60*1000L).setPersisted(true).build());
  android.content.SharedPreferences p=c.getSharedPreferences("notice_state",MODE_PRIVATE);
  long now=System.currentTimeMillis();
  if(s.getPendingJob(ONCE)==null&&now-p.getLong("last_check",0L)>120000L)s.schedule(new JobInfo.Builder(ONCE,name).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).build());
 }
 public static void wake(Context c){
  if(!supported()||!permitted(c))return;
  JobScheduler s=c.getSystemService(JobScheduler.class);
  if(s.getPendingJob(ONCE)==null)s.schedule(new JobInfo.Builder(ONCE,new ComponentName(c,NoticeJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).build());
 }
 public static void push(Context c,String actor,String ids){
  if(!supported()||!permitted(c)||!actor.matches("[a-f0-9]{64}")||ids.length()>1300)return;
  android.content.SharedPreferences state=c.getSharedPreferences("notice_state",MODE_PRIVATE);
  long epoch=SESSION_EPOCH.get();
  if(!actor.equals(state.getString("actor","")))return;
  Set<String> seen=state.getStringSet("seen",Collections.emptySet());
  boolean fresh=false;
  for(String id:ids.split(","))if(id.matches("[a-f0-9]{64}")&&!seen.contains(id)){fresh=true;break;}
  if(!fresh)return;
  NotificationManager nm=c.getSystemService(NotificationManager.class);
  nm.createNotificationChannel(new NotificationChannel(CHANNEL,"School updates",NotificationManager.IMPORTANCE_DEFAULT));
  Intent intent=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
  PendingIntent tap=PendingIntent.getActivity(c,NOTICE,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
  // No school records or financial amounts are included in the push payload.
  Notification note=new Notification.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("School update").setContentText("Open your school app for new updates.").setVisibility(Notification.VISIBILITY_PRIVATE).setContentIntent(tap).setOnlyAlertOnce(true).setAutoCancel(true).build();
  if(epoch!=SESSION_EPOCH.get())return;
  nm.notify(NOTICE,note);
  if(epoch!=SESSION_EPOCH.get()){nm.cancel(NOTICE);return;}
  wake(c);
 }
 public static void clear(Context c){
  SESSION_EPOCH.incrementAndGet();
  c.getSharedPreferences("notice_state",MODE_PRIVATE).edit().clear().commit();
  c.getSystemService(NotificationManager.class).cancel(NOTICE);
 }
 @Override public boolean onStartJob(JobParameters params){
  Thread worker=new Thread(()->{
   try{synchronized(LOCK){if(!Thread.currentThread().isInterrupted()&&permitted(this))check();}}
   catch(Exception ignored){/* Network unavailable or server asleep: preserve state. */}
   finally{tasks.remove(params.getJobId(),Thread.currentThread());if(!Thread.currentThread().isInterrupted())jobFinished(params,false);}
  },"school-notices");
  tasks.put(params.getJobId(),worker);worker.start();return true;
 }
 @Override public boolean onStopJob(JobParameters params){Thread t=tasks.remove(params.getJobId());if(t!=null)t.interrupt();return false;}
 private JSONObject response(HttpURLConnection conn)throws Exception{
  int status=conn.getResponseCode();
  if(status==401||status==403||status==409||(status>=300&&status<400))return null;
  if(status!=200)throw new IOException("Notice feed unavailable");
  if(conn.getContentType()==null||!conn.getContentType().contains("application/json"))throw new IOException("Unexpected response");
  try(InputStream in=conn.getInputStream()){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] bytes=new byte[2048];int n;while((n=in.read(bytes))!=-1){if(out.size()+n>131072)throw new IOException("Notice response too large");out.write(bytes,0,n);}return new JSONObject(out.toString("UTF-8"));}
 }
 private void registerPortal(String path,String cookie,JSONObject result,String token)throws Exception{
  if(!result.optBoolean("push_enabled")||token.isEmpty()||result.optString("push_csrf").isEmpty())return;
  HttpURLConnection conn=(HttpURLConnection)new URL(EndpointPolicy.BASE+path).openConnection();
  try{
   conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(10000);conn.setReadTimeout(10000);conn.setRequestMethod("POST");conn.setDoOutput(true);
   conn.setRequestProperty("Cookie",cookie);conn.setRequestProperty("Content-Type","application/x-www-form-urlencoded");
   String data="_csrf="+URLEncoder.encode(result.getString("push_csrf"),"UTF-8")+"&push_token="+URLEncoder.encode(token,"UTF-8")+"&package="+URLEncoder.encode(getPackageName(),"UTF-8");
   try(OutputStream out=conn.getOutputStream()){out.write(data.getBytes(StandardCharsets.UTF_8));}
   response(conn);
  }finally{conn.disconnect();}
 }
 private JSONObject fetch()throws Exception{
  String role=BuildConfig.ROLE,path,cookie=null;
  JSONObject sms=null;
  if("sms".equals(role)){
   sms=new JSONObject(new Vault(this).read());
   if(!sms.optString("device").matches("[1-9][0-9]{0,8}")||!sms.optString("key").matches("[A-Za-z0-9_-]{43}")||!sms.optString("scope").matches("[a-f0-9]{64}")||!SchoolBinding.matches(BuildConfig.INSTITUTE_CODE,BuildConfig.SCHOOL_SCOPE,sms.optString("code"),sms.optString("school_scope")))return null;
   path="/api/sms/devices/"+sms.getString("device")+"/notification-feed";
  }else{
   if("parents".equals(role)){
    String code=BuildConfig.INSTITUTE_CODE;
    if(!code.matches("[A-Z0-9][A-Z0-9-]{2,39}"))return null;
    path="/parents/"+code+"/app/notification-feed";
   }else path="/"+role+"-app/notification-feed";
   cookie=CookieManager.getInstance().getCookie(EndpointPolicy.BASE+path);
   if(cookie==null||cookie.isEmpty())return null;
  }
  HttpURLConnection conn=(HttpURLConnection)new URL(EndpointPolicy.BASE+path).openConnection();
  try{
   conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(15000);conn.setReadTimeout(15000);
   conn.setRequestProperty("Accept","application/json");
   if(sms!=null){
    conn.setRequestMethod("POST");conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json");
    conn.setRequestProperty("X-Institute-Code",sms.getString("code"));conn.setRequestProperty("X-Device-Scope",sms.getString("scope"));conn.setRequestProperty("Authorization","Bearer "+sms.getString("key"));
    JSONObject payload=new JSONObject();String token=SchoolPushService.token(this);if(!token.isEmpty())payload.put("push_token",token).put("package",getPackageName());
   try(OutputStream out=conn.getOutputStream()){out.write(payload.toString().getBytes(StandardCharsets.UTF_8));}
   }else conn.setRequestProperty("Cookie",cookie);
   JSONObject result=response(conn);
   if(sms==null&&result!=null&&result.optBoolean("push_enabled"))try{registerPortal(path,cookie,result,SchoolPushService.token(this));}catch(Exception ignored){/* Polling still works. */}
   return result;
  }finally{conn.disconnect();}
 }
 private void check()throws Exception{
  android.content.SharedPreferences state=getSharedPreferences("notice_state",MODE_PRIVATE);
  long epoch=SESSION_EPOCH.get();
  JSONObject result=fetch();if(Thread.currentThread().isInterrupted()||epoch!=SESSION_EPOCH.get())return;
  if(result==null){clear(this);return;}
  String actor=result.getString("actor");if(!actor.matches("[a-f0-9]{64}"))throw new IOException();
  boolean same=actor.equals(state.getString("actor",""));
  Set<String> prior=same?new HashSet<>(state.getStringSet("seen",Collections.emptySet())):new HashSet<>();
  JSONArray events=result.getJSONArray("events");Set<String> seen=new HashSet<>(prior);List<JSONObject> fresh=new ArrayList<>();
  for(int i=0;i<Math.min(events.length(),80);i++){
   JSONObject event=events.getJSONObject(i);String id=event.getString("id");if(!id.matches("[a-f0-9]{64}"))continue;
   if(seen.add(id))fresh.add(event);
  }
  if(!same)getSystemService(NotificationManager.class).cancel(NOTICE);
  if(seen.size()>500){seen.clear();for(int i=0;i<Math.min(events.length(),80);i++)seen.add(events.getJSONObject(i).getString("id"));}
  if(epoch!=SESSION_EPOCH.get())return;
  if(!fresh.isEmpty()&&permitted(this)){
   JSONObject first=fresh.get(0);
   // No pupil names, marks, phone numbers or financial data on the lock screen.
   String title=first.optString("title","School update"),body=first.optString("body","Open your app for details.");
   if(fresh.size()>1)body+=" · "+(fresh.size()-1)+" more update(s)";
   Intent intent=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
   PendingIntent tap=PendingIntent.getActivity(this,NOTICE,intent,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
   Notification publicVersion=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("School update").setContentText("Open your school app").build();
   Notification notice=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title).setContentText(body).setStyle(new Notification.BigTextStyle().bigText(body)).setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(publicVersion).setOnlyAlertOnce(true).setContentIntent(tap).setAutoCancel(true).build();
   getSystemService(NotificationManager.class).notify(NOTICE,notice);
  }
  if(epoch!=SESSION_EPOCH.get()){getSystemService(NotificationManager.class).cancel(NOTICE);return;}
  state.edit().putString("actor",actor).putStringSet("seen",seen).putLong("last_check",System.currentTimeMillis()).commit();
 }
}
