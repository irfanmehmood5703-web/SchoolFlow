package com.schoolflow.clients;
import android.content.Context;
import android.os.Build;
import com.google.android.gms.tasks.Tasks;
import com.google.firebase.FirebaseApp;
import com.google.firebase.FirebaseOptions;
import com.google.firebase.messaging.FirebaseMessaging;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import org.json.JSONObject;
import java.util.concurrent.TimeUnit;

/** Receives opaque wake signals; private content always comes from SchoolFlow. */
public final class SchoolPushService extends FirebaseMessagingService {
 static synchronized boolean ready(Context context) {
  if(!NoticeJob.supported()||BuildConfig.FCM_CONFIG.isEmpty()||BuildConfig.SCHOOL_SCOPE.isEmpty())return false;
  String expected="com.schoolflow.schools.s"+BuildConfig.SCHOOL_SCOPE+"."+BuildConfig.ROLE+".test";
  if(!context.getPackageName().equals(expected))return false;
  try {
   if(FirebaseApp.getApps(context).isEmpty()){
    JSONObject cfg=new JSONObject(BuildConfig.FCM_CONFIG);
    FirebaseOptions options=new FirebaseOptions.Builder().setApplicationId(cfg.getString("app_id")).setApiKey(cfg.getString("api_key")).setGcmSenderId(cfg.getString("sender_id")).setProjectId(cfg.getString("project_id")).build();
    FirebaseApp.initializeApp(context,options);
   }
   return true;
  }catch(Exception ignored){return false;}
 }
 static String token(Context context){
  if(!ready(context))return "";
  try{return Tasks.await(FirebaseMessaging.getInstance().getToken(),8,TimeUnit.SECONDS);}
  catch(Exception ignored){return "";}
 }
 @Override public void onNewToken(String token){NoticeJob.wake(this);}
 @Override public void onMessageReceived(RemoteMessage message){
  if(!"schoolflow-update".equals(message.getData().get("kind")))return;
  String actor=message.getData().get("actor"),ids=message.getData().get("ids");
  if(actor==null||ids==null)return;
  NoticeJob.push(this,actor,ids);
 }
}
