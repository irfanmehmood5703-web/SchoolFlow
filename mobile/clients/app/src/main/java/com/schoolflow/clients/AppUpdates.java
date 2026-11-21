package com.schoolflow.clients;
import android.app.*;
import android.content.*;
import android.net.Uri;
import android.os.Build;
import org.json.JSONObject;
import java.net.*;
import java.io.*;
import java.util.concurrent.*;

final class AppUpdates {
 private static final ExecutorService WORK=Executors.newSingleThreadExecutor();
 static void check(Activity activity) {
  if(BuildConfig.SCHOOL_SCOPE.isEmpty()||"sms".equals(BuildConfig.ROLE))return;
  WORK.execute(()->{
   HttpURLConnection connection=null;
   try {
    String endpoint=EndpointPolicy.BASE+"/api/mobile-app/update/"+BuildConfig.SCHOOL_SCOPE+"/"+BuildConfig.ROLE;
    connection=(HttpURLConnection)new URL(endpoint).openConnection();
    connection.setConnectTimeout(7000);connection.setReadTimeout(7000);
    if(connection.getResponseCode()!=200)return;
    ByteArrayOutputStream out=new ByteArrayOutputStream();
    try(InputStream input=connection.getInputStream()){
     byte[] bytes=new byte[2048];int n;
     while((n=input.read(bytes))!=-1){if(out.size()+n>8192)return;out.write(bytes,0,n);}
    }
    JSONObject info=new JSONObject(out.toString("UTF-8"));
    if(!info.optBoolean("available"))return;
    int installed=Build.VERSION.SDK_INT>=28?(int)activity.getPackageManager().getPackageInfo(activity.getPackageName(),0).getLongVersionCode():activity.getPackageManager().getPackageInfo(activity.getPackageName(),0).versionCode;
    if(info.optInt("version_code",0)<=installed)return;
    String link=info.optString("url","");
    if(!link.startsWith(EndpointPolicy.BASE+"/apps/school/")||!link.endsWith("/"+BuildConfig.ROLE+".apk"))return;
    activity.runOnUiThread(()->new AlertDialog.Builder(activity)
      .setTitle("SchoolFlow update available")
      .setMessage("A new version of your school app is ready. Download and install it to update. Your school account stays on the server.")
      .setPositiveButton("Update", (d,w)->activity.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(link))))
      .setNegativeButton("Later",null).show());
   }catch(Exception ignored){}finally{if(connection!=null)connection.disconnect();}
  });
 }
}
