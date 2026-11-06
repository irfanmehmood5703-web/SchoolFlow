package com.schoolflow.gate;
import android.app.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.*;
import org.opencv.android.*;
import org.opencv.core.Mat;

/** Attended face gate: recognizing a face never silently posts attendance. */
public class MainActivity extends CameraActivity implements CameraBridgeViewBase.CvCameraViewListener2 {
 private static final int LOCK_REQUEST=731;
 private final Handler ui=new Handler(Looper.getMainLooper());
 private final ExecutorService worker=Executors.newSingleThreadExecutor();
 private final ExecutorService initializer=Executors.newSingleThreadExecutor();
 private final AtomicBoolean busy=new AtomicBoolean(false);
 private final RecognitionPolicy.Stable stable=new RecognitionPolicy.Stable();
 private final Map<String,Long> confirmedAt=new HashMap<>();
 private Vault vault;private volatile FaceEngine engine;
 private volatile List<RecognitionPolicy.Identity> known=Collections.emptyList();
 private JavaCameraView camera;private TextView status,personText,detail;
 private Button start,confirm;private Spinner direction;
 private volatile boolean running=false,visible=false,connected=false,clockOK=false;
 private volatile String marks="";
 /** Publish each camera result atomically; never mix a new identity with an
  * earlier frame's stability flag or timestamp across camera/UI threads. */
 private static final class Observation {
  final float[] feature;final RecognitionPolicy.Match match;final long capturedAt;final boolean stable;
  Observation(float[] feature,RecognitionPolicy.Match match,long capturedAt,boolean stable){this.feature=feature;this.match=match;this.capturedAt=capturedAt;this.stable=stable;}
 }
 private volatile Observation observation=new Observation(null,null,0,false);
 private volatile boolean readEnrollmentQr;private volatile EditText enrollmentQrTarget;
 private long processedAt,lastContact;private Runnable protectedAction;
 private final Runnable poll=new Runnable(){public void run(){if(!visible)return;try{if(vault!=null&&vault.pending()!=null)deliver();else if(vault!=null&&(!contactValid()||SystemClock.elapsedRealtime()-lastContact>40000))heartbeat();}catch(Exception e){show("Protected storage error. Reconnect only after reviewing local data.");}ui.postDelayed(this,15000);}};
 private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
 private TextView text(String value,int size){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(Color.rgb(39,39,42));v.setPadding(dp(8),dp(7),dp(8),dp(7));return v;}
 private Button button(String value,Runnable action){Button b=new Button(this);b.setText(value);b.setAllCaps(false);b.setOnClickListener(v->action.run());return b;}
 private void show(String value){ui.post(()->{if(!isFinishing())status.setText(value);});}
 private void resetFace(){observation=new Observation(null,null,0,false);stable.reset();ui.post(()->{if(confirm!=null)confirm.setEnabled(false);});}
 private boolean contactValid(){return connected&&clockOK&&SystemClock.elapsedRealtime()-lastContact<80000;}
 @Override public void onCreate(Bundle saved){
  super.onCreate(saved);getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
  getWindow().setStatusBarColor(Color.rgb(23,107,74));
  LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(Color.rgb(250,250,250));root.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
  TextView title=text("SchoolFlow Gate  ·  attended test build",23);title.setTextColor(Color.WHITE);title.setBackgroundColor(Color.rgb(23,107,74));root.addView(title);
  LinearLayout toolbar=new LinearLayout(this);toolbar.addView(button("Connection",()->protect(this::connectionDialog)));toolbar.addView(button("Enroll face",()->protect(this::enrollmentDialog)));toolbar.addView(button("Manage faces",()->protect(this::manageDialog)));
  start=button("Start camera",()->{if(running)stopCamera();else startCamera();});toolbar.addView(start);
  direction=new Spinner(this);direction.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"IN","OUT"}));toolbar.addView(direction);direction.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onItemSelected(android.widget.AdapterView<?> p,View v,int n,long id){resetFace();}public void onNothingSelected(android.widget.AdapterView<?> p){}});
  HorizontalScrollView toolbarScroll=new HorizontalScrollView(this);toolbarScroll.addView(toolbar);root.addView(toolbarScroll);
  LinearLayout body=new LinearLayout(this);
  camera=new JavaCameraView(this,CameraBridgeViewBase.CAMERA_ID_FRONT);camera.setVisibility(View.VISIBLE);camera.setMaxFrameSize(640,480);camera.setCvCameraViewListener(this);
  body.addView(camera,new LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.MATCH_PARENT,2));
  LinearLayout panel=new LinearLayout(this);panel.setOrientation(LinearLayout.VERTICAL);
  status=text("Opening protected device storage…",16);personText=text("One clear face at a time.",21);detail=text("Verify the person, then confirm the selected IN or OUT. No certified liveness detection is included. Use fictional identities until physical testing is complete.",14);
  panel.addView(personText);panel.addView(status);panel.addView(detail);
  confirm=button("Confirm identity & mark",this::confirmIdentity);confirm.setEnabled(false);panel.addView(confirm);
  panel.addView(button("Retry connection / pending mark",()->{try{if(vault!=null&&vault.pending()!=null)deliver();else heartbeat();}catch(Exception e){show("Cannot read protected storage.");}}));
  panel.addView(button("Cancel pending submission",()->protect(this::cancelPending)));
  body.addView(scroll(panel),new LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.MATCH_PARENT,1));root.addView(body,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);
  try{vault=new Vault(this);known=vault.people();status.setText(vault.lastResult());}catch(Exception e){status.setText("Protected storage cannot be opened. Attendance is disabled; do not replace it with plaintext.");start.setEnabled(false);return;}
  initializer.execute(()->{
   try{if(!OpenCVLoader.initLocal())throw new IllegalStateException();engine=new FaceEngine(this);show("Models ready. Connect a private institute gate; set a device screen lock before enrollment.");}
   catch(Exception|LinkageError e){show("Face engine could not start. This device or build needs verification.");}
  });
 }
 @Override protected List<? extends CameraBridgeViewBase> getCameraViewList(){return camera==null?Collections.emptyList():Collections.singletonList(camera);}
 @Override public void onResume(){super.onResume();visible=true;ui.removeCallbacks(poll);ui.postDelayed(poll,1000);}
 @Override public void onPause(){visible=false;ui.removeCallbacks(poll);stopCamera();super.onPause();}
 @Override public void onDestroy(){if(camera!=null)camera.disableView();worker.shutdown();initializer.shutdown();super.onDestroy();}
 private void startCamera(){
  if(engine==null){show("Wait for the face engine to load.");return;}
  running=true;resetFace();camera.enableView();getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);start.setText("Stop camera");
 }
 private void stopCamera(){running=false;resetFace();if(camera!=null)camera.disableView();getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);if(start!=null)start.setText("Start camera");}
 public void onCameraViewStarted(int width,int height){}
 public void onCameraViewStopped(){resetFace();}
 public Mat onCameraFrame(CameraBridgeViewBase.CvCameraViewFrame frame){
  Mat rgba=frame.rgba();long now=SystemClock.elapsedRealtime();
  if(!running||engine==null||now-processedAt<500)return rgba;processedAt=now;
  try {
   if(readEnrollmentQr&&enrollmentQrTarget!=null){
    EditText target=enrollmentQrTarget;String qr=engine.readQr(rgba);
    if(qr.matches("schoolflow:(student|employee):[a-f0-9]{64}")){readEnrollmentQr=false;ui.post(()->{if(enrollmentQrTarget==target){target.setText(qr);show("Identity QR read. Press Verify card before enrolling the face.");}});}
   }
   float[] current=engine.extract(rgba);
   RecognitionPolicy.Match found=current==null?null:RecognitionPolicy.match(current,known);
   observation=new Observation(current,found,now,stable.observe(found==null?null:found.identity.key(),now));
   ui.post(()->{
    if(!visible)return;
    personText.setText(found==null?(current==null?"Show one clear face.":"Face not enrolled / match uncertain."):found.identity.label+" · "+found.identity.kind+" #"+found.identity.id);
    confirm.setEnabled(canConfirm());
   });
  }catch(Exception e){resetFace();show("This camera frame could not be recognized. No attendance was marked.");}
  return rgba;
 }
 private boolean canConfirm(){return canConfirm(observation);}
 private boolean canConfirm(Observation frame){
  if(!visible||!running||!contactValid()||!frame.stable||frame.match==null||SystemClock.elapsedRealtime()-frame.capturedAt>1500||busy.get())return false;
  String dir=direction.getSelectedItemPosition()==0?"in":"out";
  if(!marks.equals("both")&&!marks.equals(dir))return false;
  try{return vault!=null&&vault.pending()==null;}catch(Exception e){return false;}
 }
 private void confirmIdentity(){
  Observation frame=observation;
  if(!canConfirm(frame)){show("Keep the same recognized person visible and reconnect if required.");return;}
  RecognitionPolicy.Match found=frame.match;String dir=direction.getSelectedItemPosition()==0?"in":"out";String key=found.identity.key()+":"+dir;long clock=SystemClock.elapsedRealtime();
  if(clock-confirmedAt.getOrDefault(key,-30000L)<10000){show("This person/direction was just submitted. Check the result before repeating.");return;}
  new AlertDialog.Builder(this).setTitle("Verify "+found.identity.label).setMessage("Confirm this is "+found.identity.kind+" #"+found.identity.id+" and record "+dir.toUpperCase(Locale.ROOT)+"? A face score is not proof of a live person.").setNegativeButton("Cancel",null).setPositiveButton("Confirm",(dialog,which)->{
   Observation latest=observation;
   if(!canConfirm(latest)||!latest.match.identity.key().equals(found.identity.key())||!latest.match.identity.binding.equals(found.identity.binding)||!(direction.getSelectedItemPosition()==0?"in":"out").equals(dir)){show("The recognized face changed or disappeared. Try again.");return;}
   try{
    JSONObject body=new JSONObject().put("event_id",UUID.randomUUID().toString().replace("-","")).put("qr_token",found.identity.qrToken).put("identity_binding",found.identity.binding).put("direction",dir).put("occurred_at",Instant.now().toString());
    vault.queue(body);confirmedAt.put(key,SystemClock.elapsedRealtime());resetFace();show("Submitting attendance…");deliver();
   }catch(Exception e){show("Submission was not saved locally. No new mark was sent.");}
  }).show();
 }
 private void protect(Runnable action){
  if(vault==null)return;
  if(protectedAction!=null)return;
  KeyguardManager manager=(KeyguardManager)getSystemService(KEYGUARD_SERVICE);
  if(manager==null||!manager.isDeviceSecure()){new AlertDialog.Builder(this).setTitle("Set a device screen lock").setMessage("Connection changes and enrollment require this tablet’s PIN, pattern or password.").setNegativeButton("Cancel",null).setPositiveButton("Open security settings",(d,w)->startActivity(new Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS))).show();return;}
  Intent intent=manager.createConfirmDeviceCredentialIntent("SchoolFlow Gate administrator","Unlock this device to manage connection or face enrollment.");
  if(intent==null){show("A secure device credential is required.");return;}
  protectedAction=action;startActivityForResult(intent,LOCK_REQUEST);
 }
 @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==LOCK_REQUEST){Runnable action=protectedAction;protectedAction=null;if(result==RESULT_OK&&action!=null)action.run();else show("Administrator action cancelled.");}}
 private EditText input(LinearLayout box,String hint,String value,int type){EditText e=new EditText(this);e.setHint(hint);e.setText(value);e.setInputType(type);e.setSaveEnabled(false);e.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);box.addView(e);return e;}
 private LinearLayout form(){LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(18),dp(8),dp(18),dp(8));return box;}
 private ScrollView scroll(View box){ScrollView s=new ScrollView(this);s.addView(box);return s;}
 private void connectionDialog(){
  if(busy.get()){show("Wait for the current request to finish.");return;}
  try{
   JSONObject old=vault.config();LinearLayout box=form();box.addView(text("SchoolFlow server: "+EndpointPolicy.BASE,14));
   EditText code=input(box,"Private institute code",old==null?"":old.getString("code"),InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
   EditText device=input(box,"Registered face gate ID",old==null?"":String.valueOf(old.getInt("device")),InputType.TYPE_CLASS_NUMBER);
   EditText token=input(box,"Device connection key",old==null?"":old.getString("token"),InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
   box.addView(text("Use the key from Face Attendance Gates → Connect. Changing institute or gate clears this device’s local face enrollment and pending mark after confirmation.",14));
   AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Connect SchoolFlow Gate").setView(scroll(box)).setNegativeButton("Cancel",null).setPositiveButton("Save connection",null).create();dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
    try {
     String school=code.getText().toString().trim().toUpperCase(Locale.ROOT),secret=token.getText().toString().trim();int id=Integer.parseInt(device.getText().toString());EndpointPolicy.validate(EndpointPolicy.BASE,school,id,secret);
     Runnable save=()->{try{if(busy.get())throw new IllegalStateException();vault.configure(school,id,secret);known=vault.people();connected=false;clockOK=false;resetFace();dialog.dismiss();heartbeat();}catch(Exception e){show("Connection was not changed. Resolve the current request and retry.");}};
     if(vault.scopeChanged(school,id))new AlertDialog.Builder(this).setTitle("Clear previous gate data?").setMessage("Local face enrollment and any pending mark will be cleared. This does not undo attendance already received by the previous institute.").setNegativeButton("Cancel",null).setPositiveButton("Clear & reconnect",(a,b)->save.run()).show();else save.run();
    }catch(Exception e){show("Enter a private institute code, positive gate ID and valid connection key.");}
   }));dialog.show();
  }catch(Exception e){show("Cannot open protected connection settings.");}
 }
 private void enrollmentDialog(){
  if(!contactValid()){show("Verify the connection and automatic device time before enrollment.");return;}
  startCamera();LinearLayout box=form();
  EditText qr=input(box,"SchoolFlow student / employee QR value","",InputType.TYPE_CLASS_TEXT);
  enrollmentQrTarget=qr;JSONObject[] verified={null};ArrayList<float[]> samples=new ArrayList<>();long[] sampled={0};
  TextView identity=text("Scan or paste this person's SchoolFlow identity QR, then verify the card.",15);box.addView(identity);
  box.addView(button("Read identity QR from camera",()->{readEnrollmentQr=true;show("Hold the SchoolFlow identity QR clearly in front of the camera.");}));
  CheckBox permission=new CheckBox(this);permission.setText("I verified this person and permission to enroll their face on this school device.");box.addView(permission);
  TextView count=text("After card verification, remove the card and capture three live samples of the same person.",14);box.addView(count);
  qr.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int d){}public void onTextChanged(CharSequence s,int a,int b,int c){verified[0]=null;samples.clear();identity.setText("Card changed; verify it again.");}public void afterTextChanged(android.text.Editable e){}});
  box.addView(button("Verify card with SchoolFlow",()->{
   String value=qr.getText().toString().trim();
   if(!value.matches("schoolflow:(student|employee):[a-f0-9]{64}")||!contactValid()){identity.setText("Use a SchoolFlow identity QR and verified gate connection.");return;}
   if(!busy.compareAndSet(false,true)){identity.setText("Wait for the current request.");return;}
   worker.execute(()->{
    try{
     JSONObject config=vault.config();GateApi.Reply reply=new GateApi().post(config,"identity",new JSONObject().put("qr_token",value));
     if(reply.code!=200||!reply.json.getString("scope_id").equals(config.getString("scope_id")))throw new SecurityException();
     JSONObject record=new JSONObject(reply.json.toString()).put("qr_token",value);
     ui.post(()->{if(enrollmentQrTarget==qr&&qr.getText().toString().trim().equals(value)){verified[0]=record;samples.clear();identity.setText(record.optString("name")+" · "+record.optString("person_kind")+" #"+record.optInt("person_id"));count.setText("Identity verified. Capture three clear samples of this same person.");}});
    }catch(Exception e){ui.post(()->{if(enrollmentQrTarget==qr)identity.setText("Identity could not be verified for this school/gate. No face enrollment saved.");});}
    finally{busy.set(false);}
   });
  }));
  box.addView(button("Capture face sample",()->{
   Observation latest=observation;float[] current=latest.feature;
   if(verified[0]==null||current==null||SystemClock.elapsedRealtime()-latest.capturedAt>1500||SystemClock.elapsedRealtime()-sampled[0]<600){count.setText("Verify the card, remove it, and keep one clear live face visible.");return;}
   if(!samples.isEmpty()&&RecognitionPolicy.cosine(samples.get(0),current)<RecognitionPolicy.THRESHOLD){samples.clear();count.setText("Samples did not match the same person. Start again.");return;}
   if(samples.size()<3){samples.add(current.clone());sampled[0]=SystemClock.elapsedRealtime();}count.setText(samples.size()+" / 3 samples captured.");
  }));
  AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Enroll verified identity").setView(scroll(box)).setNegativeButton("Cancel",null).setPositiveButton("Save local enrollment",null).create();
  dialog.setOnDismissListener(d->{readEnrollmentQr=false;if(enrollmentQrTarget==qr)enrollmentQrTarget=null;});
  dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
   try{
    if(!permission.isChecked()||samples.size()!=3||!contactValid()||verified[0]==null)throw new IllegalArgumentException();
    JSONObject person=verified[0];
    if(!person.getString("scope_id").equals(vault.config().getString("scope_id")))throw new SecurityException();
    RecognitionPolicy.Identity value=new RecognitionPolicy.Identity(person.getString("person_kind"),person.getInt("person_id"),person.getString("name"),person.getString("qr_token"),person.getString("identity_binding"),samples);
   RecognitionPolicy.Identity duplicate=RecognitionPolicy.enrollmentConflict(value,known);
    if(duplicate!=null){count.setText("This face resembles another enrolled identity. Review both; do not assign it again.");return;}
    vault.enroll(value);known=vault.people();resetFace();dialog.dismiss();show("Verified local face enrollment saved. Validate recognition with fictional trials first.");
   }catch(Exception e){count.setText("Verify the current card/connection, permission and all three samples.");}
  }));dialog.show();
 }
 private void manageDialog(){
  try{
   List<RecognitionPolicy.Identity> people=vault.people();String[] labels=new String[people.size()];for(int i=0;i<people.size();i++)labels[i]=people.get(i).label+" · "+people.get(i).key();
   new AlertDialog.Builder(this).setTitle("Local face enrollment ("+people.size()+")").setItems(labels,(d,index)->new AlertDialog.Builder(this).setTitle("Delete local enrollment?").setMessage("This stops local recognition for "+people.get(index).label+". It does not undo saved attendance.").setNegativeButton("Cancel",null).setPositiveButton("Delete",(a,b)->{try{vault.remove(people.get(index).key());known=vault.people();resetFace();show("Local enrollment deleted.");}catch(Exception e){show("Enrollment was not deleted.");}}).show()).setNegativeButton("Close",null).show();
  }catch(Exception e){show("Cannot read protected enrollments.");}
 }
 private void cancelPending(){
  if(busy.get()){show("Wait for the current request to finish.");return;}
  try{JSONObject pending=vault.pending();if(pending==null){show("No pending submission.");return;}new AlertDialog.Builder(this).setTitle("Cancel retry?").setMessage("A server may already have received this mark. Cancelling retry does not undo it. Check web scan history before a manual correction.").setNegativeButton("Keep pending",null).setPositiveButton("Cancel retry",(d,w)->{try{vault.finish(pending.getJSONObject("body").getString("event_id"),"Retry cancelled. Verify the web scan history.");show(vault.lastResult());}catch(Exception e){show("Cannot cancel this submission.");}}).show();}catch(Exception e){show("Cannot read the pending submission.");}
 }
 private void heartbeat(){
  if(vault==null||!visible||!busy.compareAndSet(false,true))return;
  worker.execute(()->{
   try{
    JSONObject config=vault.config();if(config==null){show("Connect your private institute gate first.");return;}
    GateApi.Reply reply=new GateApi().post(config,"heartbeat",new JSONObject().put("model",Build.MANUFACTURER+" "+Build.MODEL).put("client_version","SchoolFlow Gate 0.1-test"));
    if(reply.code!=200){connected=false;clockOK=false;show("Connection refused ("+reply.code+"). Check the gate key/status.");return;}
    boolean changed=vault.bindScope(reply.json.getString("scope_id"));if(changed){known=vault.people();resetFace();connected=false;clockOK=false;show(vault.lastResult());return;}
    String state=reply.json.getString("status");marks=reply.json.getString("marks");lastContact=SystemClock.elapsedRealtime();clockOK=Math.abs(Duration.between(Instant.now(),OffsetDateTime.parse(reply.json.getString("server_time")).toInstant()).toMillis())<=60000;
    connected=state.equals("Pending")||state.equals("Approved");
    if(!clockOK)show("Correct automatic date/time on this device before marking.");
    else if(!connected)show("Gate is "+state+". Attendance is paused.");
    else show("Gate connected · "+config.getString("code")+" #"+config.getInt("device")+" · "+known.size()+" local identities.");
   }catch(Exception e){connected=false;clockOK=false;show("Connection unavailable. New attendance is paused; no face data was uploaded.");}
   finally{busy.set(false);ui.post(()->confirm.setEnabled(canConfirm()));}
  });
 }
 private void deliver(){
  if(vault==null||!visible||!busy.compareAndSet(false,true))return;
  worker.execute(()->{
   try{
    JSONObject pending=vault.pending();if(pending==null)return;JSONObject body=pending.getJSONObject("body"),config=vault.config();if(config==null)return;
    long age=System.currentTimeMillis()-pending.getLong("captured_ms");
    if(age< -60000||age>14*60*1000){vault.finish(body.getString("event_id"),"Pending event expired. Check web history and use manual attendance if necessary.");show(vault.lastResult());return;}
    GateApi.Reply check=new GateApi().post(config,"heartbeat",new JSONObject().put("model",Build.MODEL).put("client_version","SchoolFlow Gate 0.1-test"));
    if(check.code!=200){connected=false;show("Cannot verify the gate before retry. Pending mark retained.");return;}
    String scope=check.json.getString("scope_id");
    if(!scope.equals(pending.getString("scope_id"))){vault.bindScope(scope);known=vault.people();resetFace();connected=false;clockOK=false;show(vault.lastResult());return;}
    String gateStatus=check.json.getString("status");
    if(!(gateStatus.equals("Pending")||gateStatus.equals("Approved"))){connected=false;show("Gate is paused. No pending mark was posted.");return;}
    if(Math.abs(Duration.between(Instant.now(),OffsetDateTime.parse(check.json.getString("server_time")).toInstant()).toMillis())>60000){connected=false;show("Correct device time before retrying the pending mark.");return;}
    GateApi.Reply reply=new GateApi().post(config,"events",body);
    if(reply.code==200||reply.code==201){
     String outcome=reply.json.getString("outcome");if(!Arrays.asList("Marked","Already marked","Not marked").contains(outcome))throw new IllegalStateException();
     String message=outcome+": "+reply.json.optString("reason","");vault.finish(body.getString("event_id"),message);show(message);
    }else if(reply.code==401||reply.code==403){connected=false;show("Gate authorization refused. Pending event retained; update the key or review status.");}
    else if(reply.code==409||reply.code==422||(reply.code>=300&&reply.code<400)){vault.finish(body.getString("event_id"),"Submission refused ("+reply.code+"). Verify web history before correcting manually.");show(vault.lastResult());}
    else show("Temporary server problem. The identical event remains pending for retry.");
   }catch(Exception e){connected=false;show("No confirmed reply. The exact event is retained privately for retry; new scans are paused.");}
   finally{busy.set(false);ui.post(()->confirm.setEnabled(canConfirm()));}
  });
 }
}
