package com.schoolflow.clients;
import android.app.*;
import android.Manifest;
import android.content.pm.PackageManager;
import android.content.*;
import android.net.Uri;
import android.os.Bundle;
import android.print.PrintManager;
import android.webkit.*;
import android.widget.*;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.*;
final class PortalScreen {
 private final Activity a;private WebView web;private TextView status;
 private static final int MICROPHONE_PERMISSION=91;
 private PermissionRequest microphone;private boolean foreground;
 private ValueCallback<Uri[]> files;private String downloadUrl;private final ExecutorService io=Executors.newSingleThreadExecutor();
 PortalScreen(Activity activity){a=activity;}
 private String startUrl(){return EndpointPolicy.BASE+"/mobile/"+BuildConfig.ROLE+(BuildConfig.INSTITUTE_CODE.isEmpty()?"":"?school="+BuildConfig.INSTITUTE_CODE);}
 void show(Bundle state){
  LinearLayout root=new LinearLayout(a);root.setOrientation(LinearLayout.VERTICAL);LinearLayout bar=new LinearLayout(a);
  Button home=new Button(a);home.setText("Home");home.setOnClickListener(v->web.loadUrl(startUrl()));bar.addView(home);
  Button reload=new Button(a);reload.setText("Reload");reload.setOnClickListener(v->web.reload());bar.addView(reload);
  Button print=new Button(a);print.setText("Print");print.setOnClickListener(v->((PrintManager)a.getSystemService(Context.PRINT_SERVICE)).print("SchoolFlow",web.createPrintDocumentAdapter("SchoolFlow"),null));bar.addView(print);
  Button clear=new Button(a);clear.setText("Sign out");clear.setOnClickListener(v->new AlertDialog.Builder(a).setMessage("Clear this app’s school session?").setPositiveButton("Sign out",(d,w)->{CookieManager.getInstance().removeAllCookies(ok->{web.clearHistory();web.clearCache(true);WebStorage.getInstance().deleteAllData();web.loadUrl(startUrl());});}).setNegativeButton("Cancel",null).show());bar.addView(clear);
  root.addView(bar);status=new TextView(a);root.addView(status);web=new WebView(a);root.addView(web,new LinearLayout.LayoutParams(-1,0,1));a.setContentView(root);
  WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setSafeBrowsingEnabled(true);settings.setJavaScriptCanOpenWindowsAutomatically(false);settings.setSupportMultipleWindows(false);
  CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
  web.setWebViewClient(new WebViewClient(){
   @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest req){if(EndpointPolicy.allowed(req.getUrl().toString()))return false;status.setText("This link is outside SchoolFlow. Open it in your browser if needed.");return true;}
   @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest req){String url=req.getUrl().toString();if(EndpointPolicy.allowed(url)||url.startsWith("data:image/"))return null;return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));}
   @Override public void onReceivedSslError(WebView view,android.webkit.SslErrorHandler handler,android.net.http.SslError error){handler.cancel();status.setText("Secure connection failed. Check your phone date and network.");}
   @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){status.setText("Loading school…");}
   @Override public void onPageFinished(WebView view,String url){status.setText("");CookieManager.getInstance().flush();}
   @Override public void onReceivedError(WebView view,WebResourceRequest req,WebResourceError error){if(req.isForMainFrame())status.setText("School unavailable. Check internet, then tap Reload.");}
  });
  web.setWebChromeClient(new WebChromeClient(){
   @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params){if(files!=null)files.onReceiveValue(null);files=callback;try{a.startActivityForResult(params.createIntent(),41);}catch(ActivityNotFoundException e){files.onReceiveValue(null);files=null;status.setText("No file chooser installed.");}return true;}
   @Override public void onPermissionRequest(PermissionRequest request){a.runOnUiThread(()->requestMicrophone(request));}
   @Override public void onPermissionRequestCanceled(PermissionRequest request){a.runOnUiThread(()->{if(microphone==request)microphone=null;});}
  });
  web.setDownloadListener((url,agent,disposition,mime,length)->{if(!EndpointPolicy.allowed(url))return;downloadUrl=url;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(mime==null?"application/octet-stream":mime).putExtra(Intent.EXTRA_TITLE,URLUtil.guessFileName(url,disposition,mime));try{a.startActivityForResult(i,42);}catch(ActivityNotFoundException e){status.setText("File saving is unavailable on this phone.");}});
  if(state==null||web.restoreState(state)==null)web.loadUrl(startUrl());
 }
 void result(int code,int result,Intent data){if(code==41&&files!=null){files.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));files=null;}
  if(code==42&&result==Activity.RESULT_OK&&data!=null&&data.getData()!=null&&downloadUrl!=null){Uri target=data.getData();String url=downloadUrl;downloadUrl=null;String cookies=CookieManager.getInstance().getCookie(url);io.execute(()->{HttpURLConnection conn=null;try{conn=(HttpURLConnection)new URL(url).openConnection();conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(20000);conn.setReadTimeout(30000);if(cookies!=null)conn.setRequestProperty("Cookie",cookies);if(conn.getResponseCode()!=200)throw new IOException();try(InputStream in=conn.getInputStream();OutputStream out=a.getContentResolver().openOutputStream(target)){if(out==null)throw new IOException();byte[] buffer=new byte[8192];int n;long total=0;while((n=in.read(buffer))!=-1){total+=n;if(total>25*1024*1024)throw new IOException();out.write(buffer,0,n);}}a.runOnUiThread(()->status.setText("File saved."));}catch(Exception e){a.runOnUiThread(()->status.setText("Download failed. Sign in again and retry."));}finally{if(conn!=null)conn.disconnect();}});}
 }
 private void denyMicrophone(){if(microphone!=null){microphone.deny();microphone=null;}}
 private boolean permitted(PermissionRequest request){return !a.isFinishing()&&!a.isDestroyed()&&PortalPermissions.microphone(request.getOrigin().toString(),web.getUrl(),request.getResources(),foreground);}
 private void requestMicrophone(PermissionRequest request){
  denyMicrophone();
  if(!permitted(request)){request.deny();return;}
  if(a.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED){request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});return;}
  microphone=request;status.setText("Allow the microphone, then press Record again if needed. No recording is sent automatically.");
  a.requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},MICROPHONE_PERMISSION);
 }
 void permissions(int code,int[] results){
  if(code!=MICROPHONE_PERMISSION)return;
  PermissionRequest request=microphone;microphone=null;
  if(request==null)return;
  if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED&&permitted(request))request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
  else{request.deny();status.setText("Microphone unavailable. Retry Record while this app is open, or attach an audio file.");}
 }
 boolean back(){if(web.canGoBack()){web.goBack();return true;}return false;}
 void save(Bundle out){web.saveState(out);}void pause(){foreground=false;denyMicrophone();web.evaluateJavascript("window.dispatchEvent(new Event('schoolflow:pause'));",null);web.onPause();CookieManager.getInstance().flush();}void resume(){foreground=true;web.onResume();}
 void destroy(){foreground=false;denyMicrophone();if(files!=null)files.onReceiveValue(null);web.destroy();io.shutdownNow();}
}
