package com.schoolflow.clients;
import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;
import android.telephony.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
final class SmsScreen {
 private final Activity a;private final Vault vault;private final ExecutorService io=Executors.newSingleThreadExecutor();
 private JSONObject config=new JSONObject();private JSONObject job;private TextView status,preview;private EditText code,id,key;private Spinner sims;private Button connect,fetch,send,report;private boolean busy=false,awaiting=false,active=true;private BroadcastReceiver receiver;private int completed,expected;private boolean failed;
 private final ArrayList<Integer> subscriptionIds=new ArrayList<>();
 SmsScreen(Activity activity){a=activity;vault=new Vault(a);}
 void show(){
  LinearLayout root=new LinearLayout(a);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(20,20,20,20);ScrollView scroll=new ScrollView(a);scroll.addView(root);a.setContentView(scroll);
  TextView title=new TextView(a);title.setText("SchoolFlow · School SIM SMS");title.setTextSize(22);root.addView(title);
  TextView help=new TextView(a);help.setText("Connect the phone registered by your school owner. Review each message before sending. SIM/network charges apply. No background sending or automatic retry.");root.addView(help);
  code=field(root,"Institute Code",false);id=field(root,"Phone ID",false);id.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);key=field(root,"Connection Key",true);
  connect=button(root,"Connect school phone",this::connect);
  button(root,"Enable SMS permission / Load SIMs",()->{if(a.checkSelfPermission(Manifest.permission.SEND_SMS)!=PackageManager.PERMISSION_GRANTED||a.checkSelfPermission(Manifest.permission.READ_PHONE_STATE)!=PackageManager.PERMISSION_GRANTED){a.requestPermissions(new String[]{Manifest.permission.SEND_SMS,Manifest.permission.READ_PHONE_STATE},13);status.setText("After allowing permission, tap this button again to load SIMs.");}else loadSims();});
  sims=new Spinner(a);root.addView(sims);status=new TextView(a);root.addView(status);preview=new TextView(a);preview.setTextSize(17);root.addView(preview);
  fetch=button(root,"Review next queued SMS",this::claim);send=button(root,"Send reviewed SMS",this::confirm);report=button(root,"Retry result upload (does not resend)",this::report);
  button(root,"Resolve uncertain local job",()->{if(job==null||awaiting||busy)return;new AlertDialog.Builder(a).setMessage("First inspect this message in the phone’s SMS app and the school outbox. Clearing this local record never retries a started message. Continue?").setPositiveButton("Clear local record",(d,w)->{try{config.remove("job");config.remove("stage");config.remove("outcome");vault.save(config.toString());job=null;preview.setText("");status.setText("Local record cleared. Review ambiguous outbox entries with your school owner.");controls();}catch(Exception e){status.setText("Could not save private state.");}}).setNegativeButton("Cancel",null).show();});
  try{config=new JSONObject(vault.read());code.setText(config.optString("code"));id.setText(config.optString("device"));key.setText(config.optString("key"));job=config.optJSONObject("job");if(job!=null){preview.setText(job.optString("phone")+"\n\n"+job.optString("text"));status.setText("Saved job recovered. A started/uncertain send will not be resent.");}}catch(Exception e){status.setText("Private storage unavailable. Reinstall or reconnect only after the school owner reviews pending messages.");busy=true;}
  controls();
 }
 private EditText field(LinearLayout root,String label,boolean secret){EditText v=new EditText(a);v.setHint(label);v.setSingleLine(true);if(secret)v.setInputType(129);root.addView(v);return v;}
 private Button button(LinearLayout root,String label,Runnable run){Button b=new Button(a);b.setText(label);b.setOnClickListener(v->run.run());root.addView(b);return b;}
 private void controls(){if(connect==null)return;connect.setEnabled(!busy&&job==null);fetch.setEnabled(!busy&&job==null&&config.has("scope"));send.setEnabled(!busy&&job!=null&&"claimed".equals(config.optString("stage")));report.setEnabled(!busy&&!awaiting&&job!=null&&config.has("outcome"));}
 private void task(Callable<String> work){if(busy)return;busy=true;controls();io.execute(()->{String text;try{text=work.call();}catch(Exception e){text="Connection failed or action refused. No automatic resend. Check the school outbox.";}final String msg=text;a.runOnUiThread(()->{busy=false;status.setText(msg);controls();});});}
 private JSONObject call(String action,JSONObject body) throws Exception {
  String did=config.getString("device");if(!did.matches("[1-9][0-9]{0,8}"))throw new Exception();URL u=new URL(EndpointPolicy.BASE+"/api/sms/devices/"+did+"/"+action);HttpURLConnection c=(HttpURLConnection)u.openConnection();try{c.setInstanceFollowRedirects(false);c.setConnectTimeout(20000);c.setReadTimeout(20000);c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("X-Institute-Code",config.getString("code"));c.setRequestProperty("Authorization","Bearer "+config.getString("key"));if(config.has("scope"))c.setRequestProperty("X-Device-Scope",config.getString("scope"));try(OutputStream out=c.getOutputStream()){out.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}if(c.getResponseCode()!=200)throw new IOException("Action refused");try(InputStream in=c.getInputStream()){ByteArrayOutputStream buffer=new ByteArrayOutputStream();byte[] block=new byte[2048];int n;while((n=in.read(block))!=-1){if(buffer.size()+n>16384)throw new IOException();buffer.write(block,0,n);}return new JSONObject(buffer.toString("UTF-8"));}}finally{c.disconnect();}
 }
 private void connect(){String school=code.getText().toString().trim().toUpperCase(Locale.ROOT),device=id.getText().toString().trim(),secret=key.getText().toString().trim();if(!school.matches("[A-Z0-9][A-Z0-9-]{2,39}")||!device.matches("[1-9][0-9]{0,8}")||!secret.matches("[A-Za-z0-9_-]{43}")){status.setText("Check institute code, numeric phone ID and connection key.");return;}task(()->{config=new JSONObject().put("code",school).put("device",device).put("key",secret);JSONObject h=call("heartbeat",new JSONObject());config.put("scope",h.getString("scope"));vault.save(config.toString());return "Connected: "+h.getString("name")+" · "+h.getString("campus");});}
 private void claim(){task(()->{JSONObject h=call("heartbeat",new JSONObject());if(!h.getString("scope").equals(config.getString("scope")))throw new IOException();JSONObject response=call("claim",new JSONObject());job=response.optJSONObject("job");if(job==null)return "No queued SMS for this phone.";config.put("job",job).put("stage","claimed");config.remove("outcome");vault.save(config.toString());a.runOnUiThread(()->preview.setText(job.optString("phone")+"\n\n"+job.optString("text")));return "Review recipient and message, select the SIM, then confirm.";});}
 @SuppressWarnings("MissingPermission") private void loadSims(){subscriptionIds.clear();ArrayList<String> labels=new ArrayList<>();SubscriptionManager manager=(SubscriptionManager)a.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE);List<SubscriptionInfo> active=manager.getActiveSubscriptionInfoList();if(active!=null)for(SubscriptionInfo info:active){subscriptionIds.add(info.getSubscriptionId());labels.add("SIM "+(info.getSimSlotIndex()+1)+" · "+info.getCarrierName());}sims.setAdapter(new ArrayAdapter<>(a,android.R.layout.simple_spinner_dropdown_item,labels));status.setText(labels.isEmpty()?"No active SIM found.":"Select the school SIM before sending.");}
 private JSONObject reference() throws Exception{return new JSONObject().put("id",job.getString("id")).put("token",job.getString("token"));}
 private void confirm(){
  if(job==null||!"claimed".equals(config.optString("stage")))return;
  if(a.checkSelfPermission(Manifest.permission.SEND_SMS)!=PackageManager.PERMISSION_GRANTED||a.checkSelfPermission(Manifest.permission.READ_PHONE_STATE)!=PackageManager.PERMISSION_GRANTED||subscriptionIds.isEmpty()){status.setText("Enable permission and load an active school SIM first.");return;}
  int selected=sims.getSelectedItemPosition();if(selected<0||selected>=subscriptionIds.size())return;final int subscription=subscriptionIds.get(selected);
  SmsManager manager=SmsManager.getSmsManagerForSubscriptionId(subscription);ArrayList<String> parts=manager.divideMessage(job.optString("text"));
  new AlertDialog.Builder(a).setTitle("Send using school SIM?").setMessage(job.optString("phone")+"\n"+parts.size()+" SMS part(s). Your SIM package/network charges apply.").setNegativeButton("Cancel",null).setPositiveButton("Send once",(d,w)->dispatch(manager,parts)).show();
 }
 private void dispatch(SmsManager manager,ArrayList<String> parts){if(job==null||!"claimed".equals(config.optString("stage")))return;task(()->{
  // Persist uncertainty before requesting dispatch. A lost response or process
  // restart must never call SmsManager again for this job.
  config.put("stage","started").put("outcome","unknown");vault.save(config.toString());call("start",reference());
  a.runOnUiThread(()->sendParts(manager,parts));return "Submitting to the phone network. Do not retry this message.";
 });}
 @SuppressWarnings("MissingPermission") private void sendParts(SmsManager manager,ArrayList<String> parts){
  if(!active||a.isFinishing()||a.isDestroyed()){status.setText("Send paused. Review the uncertain outbox entry; no automatic resend.");return;}
  awaiting=true;controls();
  String action=a.getPackageName()+".SENT."+UUID.randomUUID();completed=0;expected=parts.size();failed=false;
  final java.util.Set<Integer> seenParts=new java.util.HashSet<>();
  receiver=new BroadcastReceiver(){@Override public void onReceive(Context context,Intent intent){if(!seenParts.add(intent.getIntExtra("part",-1)))return;completed++;if(getResultCode()!=Activity.RESULT_OK)failed=true;if(completed==expected){unregister();finishResult(failed?"unknown":"sent");}}};
  if(Build.VERSION.SDK_INT>=33)a.registerReceiver(receiver,new IntentFilter(action),Context.RECEIVER_NOT_EXPORTED);else a.registerReceiver(receiver,new IntentFilter(action));
  ArrayList<PendingIntent> callbacks=new ArrayList<>();for(int i=0;i<parts.size();i++)callbacks.add(PendingIntent.getBroadcast(a,i,new Intent(action).setPackage(a.getPackageName()).putExtra("part",i),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));
  try{manager.sendMultipartTextMessage(job.optString("phone"),null,parts,callbacks,null);}catch(Exception e){unregister();finishResult("unknown");}
 }
 private void finishResult(String outcome){awaiting=false;try{config.put("outcome",outcome);vault.save(config.toString());status.setText("Phone result: "+outcome+". Upload result to the school outbox; this will not resend.");controls();}catch(Exception e){status.setText("Result could not be saved. Review phone SMS history; do not resend.");}}
 private void report(){if(job==null||!config.has("outcome"))return;task(()->{JSONObject body=reference().put("state",config.getString("outcome")).put("detail","Android SIM submission; recipient delivery not verified");call("result",body);config.remove("job");config.remove("stage");config.remove("outcome");vault.save(config.toString());job=null;a.runOnUiThread(()->preview.setText(""));return "Result saved. This message will not be resent.";});}
 private void unregister(){if(receiver!=null){try{a.unregisterReceiver(receiver);}catch(Exception ignored){}receiver=null;}}
 void pause(){active=false;}void resume(){active=true;}
 void destroy(){active=false;unregister();io.shutdownNow();}
}
