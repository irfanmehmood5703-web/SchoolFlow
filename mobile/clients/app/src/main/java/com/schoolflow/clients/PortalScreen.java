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
import com.schoolflow.mobile.PullToRefresh;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.*;
final class PortalScreen {
 private final Activity a;private WebView web;private TextView status;
 private static final int MICROPHONE_PERMISSION=91,LOCATION_PERMISSION=92;
 private GeolocationPermissions.Callback location;private String locationOrigin,locationPage;
 private PermissionRequest microphone;private boolean foreground,loading;
 private ValueCallback<Uri[]> files;private String downloadUrl;private final ExecutorService io=Executors.newSingleThreadExecutor();
 PortalScreen(Activity activity){a=activity;}
 private String startUrl(){return EndpointPolicy.BASE+"/mobile/"+BuildConfig.ROLE+(BuildConfig.INSTITUTE_CODE.isEmpty()?"":"?school="+BuildConfig.INSTITUTE_CODE+"&scope="+BuildConfig.SCHOOL_SCOPE);}
 void show(Bundle state){
  LinearLayout root=new LinearLayout(a);root.setOrientation(LinearLayout.VERTICAL);LinearLayout bar=new LinearLayout(a);
  Button home=new Button(a);home.setText("Home");home.setOnClickListener(v->web.loadUrl(startUrl()));bar.addView(home);
  Button reload=new Button(a);reload.setText("Reload");reload.setOnClickListener(v->web.reload());bar.addView(reload);
  Button print=new Button(a);print.setText("Print");print.setOnClickListener(v->printPage());bar.addView(print);
  Button clear=new Button(a);clear.setText("Sign out");clear.setOnClickListener(v->new AlertDialog.Builder(a).setMessage("Clear this app’s school session?").setPositiveButton("Sign out",(d,w)->{CookieManager.getInstance().removeAllCookies(ok->{NoticeJob.clear(a);web.clearHistory();web.clearCache(true);WebStorage.getInstance().deleteAllData();web.loadUrl(startUrl());});}).setNegativeButton("Cancel",null).show());bar.addView(clear);
  HorizontalScrollView actions=new HorizontalScrollView(a);actions.addView(bar);if(!("owner".equals(BuildConfig.ROLE)||"parents".equals(BuildConfig.ROLE)||"teacher".equals(BuildConfig.ROLE)))root.addView(actions);TextView brand=new TextView(a);brand.setText(a.getString(com.schoolflow.clients.R.string.app_name));brand.setPadding(12,4,12,4);if(!("owner".equals(BuildConfig.ROLE)||"parents".equals(BuildConfig.ROLE)||"teacher".equals(BuildConfig.ROLE)))root.addView(brand);status=new TextView(a);status.setOnClickListener(v->{if(web!=null)web.reload();});root.addView(status);web=new WebView(a);
  root.addView(new PullToRefresh(web,this::canRefresh,this::refresh),new LinearLayout.LayoutParams(-1,0,1));a.setContentView(root);
  WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);settings.setSafeBrowsingEnabled(true);settings.setJavaScriptCanOpenWindowsAutomatically(false);settings.setSupportMultipleWindows(false);
  CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
  web.setWebViewClient(new WebViewClient(){
   @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest req){if((EndpointPolicy.BASE+"/mobile/print-current").equals(req.getUrl().toString())&&EndpointPolicy.allowed(web.getUrl())){printPage();return true;}if(EndpointPolicy.allowed(req.getUrl().toString()))return false;String target=req.getUrl().toString();if(req.isForMainFrame()&&req.hasGesture()&&EndpointPolicy.external(target)){new AlertDialog.Builder(a).setTitle("Open outside the school app?").setMessage(target).setPositiveButton("Open",(d,w)->{try{a.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(target)).addCategory(Intent.CATEGORY_BROWSABLE));}catch(ActivityNotFoundException e){status.setText("No app is available to open this link.");}}).setNegativeButton("Cancel",null).show();}else status.setText("This link cannot be opened from the school app.");return true;}
   @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest req){String url=req.getUrl().toString();if(EndpointPolicy.allowed(url)||url.startsWith("data:image/"))return null;return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));}
   @Override public void onReceivedSslError(WebView view,android.webkit.SslErrorHandler handler,android.net.http.SslError error){handler.cancel();status.setText("Secure connection failed. Check your phone date and network.");}
   @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){loading=true;denyLocation();denyMicrophone();status.setText("Loading school…");}
   @Override public void onPageFinished(WebView view,String url){loading=false;status.setText("");if(EndpointPolicy.allowed(url))web.evaluateJavascript("window.print=function(){window.location.assign('"+EndpointPolicy.BASE+"/mobile/print-current');};",null);CookieManager.getInstance().flush();if(EndpointPolicy.allowed(url)){String path=android.net.Uri.parse(url).getPath();if(path!=null&&(path.endsWith("/login")||path.endsWith("/auth/institute")))NoticeJob.clear(a);else NoticeJob.schedule(a);}}
   @Override public void onReceivedError(WebView view,WebResourceRequest req,WebResourceError error){if(req.isForMainFrame()){loading=false;status.setText("School unavailable. Check internet, then tap here to retry.");}}
  });
  web.setWebChromeClient(new WebChromeClient(){
   @Override public boolean onJsPrompt(WebView view,String url,String message,String value,JsPromptResult result){if(!EndpointPolicy.allowed(url)){result.cancel();return true;}EditText field=new EditText(a);field.setText(value==null?"":value);field.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(5000)});new AlertDialog.Builder(a).setMessage(message).setView(field).setPositiveButton("Save",(d,w)->result.confirm(field.getText().toString())).setNegativeButton("Cancel",(d,w)->result.cancel()).setOnCancelListener(d->result.cancel()).show();return true;}
   @Override public boolean onJsAlert(WebView view,String url,String message,JsResult result){if(!EndpointPolicy.allowed(url)){result.cancel();return true;}new AlertDialog.Builder(a).setMessage(message).setPositiveButton("OK",(d,w)->result.confirm()).setOnCancelListener(d->result.cancel()).show();return true;}
   @Override public boolean onJsConfirm(WebView view,String url,String message,JsResult result){if(!EndpointPolicy.allowed(url)){result.cancel();return true;}new AlertDialog.Builder(a).setMessage(message).setPositiveButton("Confirm",(d,w)->result.confirm()).setNegativeButton("Cancel",(d,w)->result.cancel()).setOnCancelListener(d->result.cancel()).show();return true;}
   @Override public boolean onShowFileChooser(WebView view,ValueCallback<Uri[]> callback,FileChooserParams params){if(files!=null)files.onReceiveValue(null);files=callback;try{a.startActivityForResult(params.createIntent(),41);}catch(ActivityNotFoundException e){files.onReceiveValue(null);files=null;status.setText("No file chooser installed.");}return true;}
   @Override public void onGeolocationPermissionsShowPrompt(String origin,GeolocationPermissions.Callback callback){
    denyLocation();
    if(!PortalPermissions.location(BuildConfig.ROLE,origin,web.getUrl(),foreground)){callback.invoke(origin,false,false);return;}
    if(a.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED){callback.invoke(origin,true,false);return;}
    location=callback;locationOrigin=origin;locationPage=web.getUrl();
    a.requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION},LOCATION_PERMISSION);
   }
   @Override public void onGeolocationPermissionsHidePrompt(){denyLocation();}
   @Override public void onPermissionRequest(PermissionRequest request){a.runOnUiThread(()->requestMicrophone(request));}
   @Override public void onPermissionRequestCanceled(PermissionRequest request){a.runOnUiThread(()->{if(microphone==request)microphone=null;});}
  });
  web.setDownloadListener((url,agent,disposition,mime,length)->{if(!EndpointPolicy.allowed(url))return;downloadUrl=url;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(mime==null?"application/octet-stream":mime).putExtra(Intent.EXTRA_TITLE,URLUtil.guessFileName(url,disposition,mime));try{a.startActivityForResult(i,42);}catch(ActivityNotFoundException e){status.setText("File saving is unavailable on this phone.");}});
  if(state==null||web.restoreState(state)==null)web.loadUrl(startUrl());
 }
 private boolean canRefresh(){
  return foreground&&!loading&&!a.isFinishing()&&!a.isDestroyed()&&EndpointPolicy.allowed(web.getUrl());
 }
 private void refresh(){
  final String page=web.getUrl();
  // Pass through to the normal WebView reload only if there is no form entry to preserve.
  web.evaluateJavascript("""
      (() => {
        const focused = document.activeElement;
        if (focused && (focused.isContentEditable || focused.matches('input, textarea, select'))) return false;
        return !Array.from(document.querySelectorAll('input, textarea, select')).some(field => {
          if (field.disabled || !field.form || field.type === 'hidden') return false;
          if (field.type === 'checkbox' || field.type === 'radio') return field.checked !== field.defaultChecked;
          if (field.nodeName === 'SELECT') {
            const options = Array.from(field.options);
            if (!field.multiple && !options.some(option => option.defaultSelected)) return field.selectedIndex > 0;
            return options.some(option => option.selected !== option.defaultSelected);
          }
          return field.type === 'file' ? field.files.length > 0 : field.value !== field.defaultValue;
        });
      })()
      """,result->{
   if(!canRefresh()||!page.equals(web.getUrl()))return;
   if("true".equals(result)){loading=true;web.reload();}
   else if("false".equals(result))status.setText("Finish or clear the form before refreshing.");
  });
 }
 private void printPage(){if(!foreground||a.isFinishing()||a.isDestroyed())return;String label=a.getString(com.schoolflow.clients.R.string.app_name);((PrintManager)a.getSystemService(Context.PRINT_SERVICE)).print(label,web.createPrintDocumentAdapter(label),null);}
 void result(int code,int result,Intent data){if(code==41&&files!=null){files.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));files=null;}
  if(code==42&&result==Activity.RESULT_OK&&data!=null&&data.getData()!=null&&downloadUrl!=null){Uri target=data.getData();String url=downloadUrl;downloadUrl=null;String cookies=CookieManager.getInstance().getCookie(url);io.execute(()->{HttpURLConnection conn=null;try{conn=(HttpURLConnection)new URL(url).openConnection();conn.setInstanceFollowRedirects(false);conn.setConnectTimeout(20000);conn.setReadTimeout(30000);if(cookies!=null)conn.setRequestProperty("Cookie",cookies);if(conn.getResponseCode()!=200)throw new IOException();try(InputStream in=conn.getInputStream();OutputStream out=a.getContentResolver().openOutputStream(target)){if(out==null)throw new IOException();byte[] buffer=new byte[8192];int n;long total=0;while((n=in.read(buffer))!=-1){total+=n;if(total>25*1024*1024)throw new IOException();out.write(buffer,0,n);}}a.runOnUiThread(()->status.setText("File saved."));}catch(Exception e){a.runOnUiThread(()->status.setText("Download failed. Sign in again and retry."));}finally{if(conn!=null)conn.disconnect();}});}
 }
 private void denyLocation(){if(location!=null){GeolocationPermissions.Callback pending=location;String origin=locationOrigin;location=null;locationOrigin=null;locationPage=null;pending.invoke(origin,false,false);}}
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
  if(code==LOCATION_PERMISSION){
   GeolocationPermissions.Callback pending=location;String origin=locationOrigin,page=locationPage;location=null;locationOrigin=null;locationPage=null;
   if(pending!=null){boolean allowed=results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED&&page!=null&&page.equals(web.getUrl())&&!a.isFinishing()&&!a.isDestroyed()&&PortalPermissions.location(BuildConfig.ROLE,origin,web.getUrl(),foreground);pending.invoke(origin,allowed,false);if(!allowed)status.setText("Precise location was not allowed. Enable it and retry Geo Attendance.");}return;
  }
  if(code!=MICROPHONE_PERMISSION)return;
  PermissionRequest request=microphone;microphone=null;
  if(request==null)return;
  if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED&&permitted(request))request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
  else{request.deny();status.setText("Microphone unavailable. Retry Record while this app is open, or attach an audio file.");}
 }
 boolean back(){if(web.canGoBack()){web.goBack();return true;}return false;}
 void save(Bundle out){web.saveState(out);}void pause(){foreground=false;denyMicrophone();denyLocation();web.evaluateJavascript("window.dispatchEvent(new Event('schoolflow:pause'));",null);web.onPause();CookieManager.getInstance().flush();}void resume(){foreground=true;web.onResume();if("owner".equals(BuildConfig.ROLE)||"parents".equals(BuildConfig.ROLE)||"teacher".equals(BuildConfig.ROLE))web.evaluateJavascript("window.dispatchEvent(new Event('schoolflow:resume'));",null);}
 void destroy(){foreground=false;denyMicrophone();denyLocation();if(files!=null)files.onReceiveValue(null);web.destroy();io.shutdownNow();}
}
