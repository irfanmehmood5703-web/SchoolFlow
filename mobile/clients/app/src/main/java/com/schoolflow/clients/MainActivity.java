package com.schoolflow.clients;
import android.app.Activity;
import android.os.Bundle;
import android.view.WindowManager;
public final class MainActivity extends Activity {
 private PortalScreen portal;
 private SmsScreen sms;
 @Override public void onCreate(Bundle state){super.onCreate(state);getWindow().setStatusBarColor(android.graphics.Color.rgb(23,107,74));getWindow().setNavigationBarColor(android.graphics.Color.rgb(23,107,74));getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,WindowManager.LayoutParams.FLAG_SECURE);
  if("sms".equals(BuildConfig.ROLE)){sms=new SmsScreen(this);sms.show();}else{portal=new PortalScreen(this);portal.show(state);}
 }
 @Override public void onBackPressed(){if(portal==null||!portal.back())super.onBackPressed();}
 @Override protected void onActivityResult(int request,int result,android.content.Intent data){super.onActivityResult(request,result,data);if(portal!=null)portal.result(request,result,data);}
 @Override protected void onPause(){if(portal!=null)portal.pause();if(sms!=null)sms.pause();super.onPause();}
 @Override protected void onResume(){super.onResume();if(portal!=null)portal.resume();if(sms!=null)sms.resume();}
 @Override protected void onSaveInstanceState(Bundle out){if(portal!=null)portal.save(out);super.onSaveInstanceState(out);}
 @Override protected void onDestroy(){if(portal!=null)portal.destroy();if(sms!=null)sms.destroy();super.onDestroy();}
}
