package com.schoolflow.gate;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.security.NetworkSecurityPolicy;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.core.app.ActivityScenario;
import android.view.*;
import android.widget.*;
import org.junit.*;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;
import org.opencv.android.OpenCVLoader;
import org.opencv.core.*;
@RunWith(AndroidJUnit4.class)
public class GateDeviceTest {
 private Context context;private File file;
 private final String token="FictionalGateKey_123456789012345678901234567890";
 @Before public void setup(){context=InstrumentationRegistry.getInstrumentation().getTargetContext();file=new File(context.getNoBackupFilesDir(),"gate.vault");file.delete();new File(file.getPath()+".bak").delete();}
 @After public void cleanup(){file.delete();}
 private RecognitionPolicy.Identity person(){float[] v=new float[128];v[0]=1;return new RecognitionPolicy.Identity("student",1,"Fictional enrolled pupil","schoolflow:student:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Arrays.asList(v,v,v));}
 private JSONObject event()throws Exception{return new JSONObject().put("event_id","fictional_event_0001").put("person_kind","student").put("person_id",1).put("direction","in").put("occurred_at",java.time.Instant.now().toString());}
 @Test public void vaultEncryptsAndPreservesExactPendingEvent()throws Exception {
  Vault a=new Vault(context);a.configure("FICTIONAL-TEST",1,token);a.bindScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");a.enroll(person());JSONObject event=event();a.queue(event);
  byte[] raw;try(FileInputStream in=new FileInputStream(file)){raw=new byte[(int)file.length()];assertEquals(raw.length,in.read(raw));}
  String ciphertext=new String(raw,StandardCharsets.ISO_8859_1);assertFalse(ciphertext.contains(token));assertFalse(ciphertext.contains("Fictional enrolled pupil"));
  Vault b=new Vault(context);assertEquals(token,b.config().getString("token"));assertEquals(1,b.people().size());assertEquals(event.toString(),b.pending().getJSONObject("body").toString());
  b.finish("wrong-event","wrong");assertNotNull(b.pending());b.finish(event.getString("event_id"),"Marked");assertNull(b.pending());assertEquals("Marked",new Vault(context).lastResult());
 }
 @Test public void changingInstituteClearsLocalTemplatesAndPending()throws Exception {
  Vault a=new Vault(context);a.configure("FICTIONAL-TEST",1,token);a.bindScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");a.enroll(person());a.queue(event());a.configure("FICTIONAL-OTHER",2,token);assertTrue(a.people().isEmpty());assertNull(a.pending());
 }
 @Test public void duplicateEnrollmentCannotChangeProtectedRoster()throws Exception {
  Vault a=new Vault(context);a.configure("FICTIONAL-TEST",1,token);a.bindScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");a.enroll(person());
  RecognitionPolicy.Identity original=person();
  RecognitionPolicy.Identity duplicate=new RecognitionPolicy.Identity("student",2,"Another fictional pupil","schoolflow:student:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","ddddddddddddddddddddddddddddddddddddddddddd",original.samples);
  boolean refused=false;try{a.enroll(duplicate);}catch(IllegalArgumentException e){refused=true;}
  assertTrue(refused);assertEquals(1,new Vault(context).people().size());
  a.enroll(original);assertEquals(1,new Vault(context).people().size());
 }
 @Test public void tamperingFailsClosed()throws Exception {
  Vault a=new Vault(context);a.configure("FICTIONAL-TEST",1,token);a.bindScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  try(RandomAccessFile f=new RandomAccessFile(file,"rw")){f.seek(f.length()-1);int old=f.read();f.seek(f.length()-1);f.write(old^1);}
  boolean failed=false;try{new Vault(context);}catch(Exception e){failed=true;}assertTrue(failed);
 }
 @Test public void modelRuntimeUsesRealNativeInferenceOnSyntheticPixels()throws Exception {
  assertTrue(OpenCVLoader.initLocal());FaceEngine engine=new FaceEngine(context);assertEquals(128,engine.runtimeFeatureShape());
  Mat blank=new Mat(480,640,CvType.CV_8UC4,new Scalar(0,0,0,255));try{assertNull(engine.extract(blank));}finally{blank.release();}
 }
 @Test public void cleartextAndCloudBackupAreDisabled(){assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted());assertEquals(0,context.getApplicationInfo().flags&ApplicationInfo.FLAG_ALLOW_BACKUP);}
 private View textView(View root,String wanted){
  if(root instanceof TextView&&wanted.contentEquals(((TextView)root).getText()))return root;
  if(root instanceof ViewGroup)for(int i=0;i<((ViewGroup)root).getChildCount();i++){View found=textView(((ViewGroup)root).getChildAt(i),wanted);if(found!=null)return found;}
  return null;
 }
 @Test public void activityLaunchesWithProtectedConnectionAndDisabledConfirmation()throws Exception {
  try(android.os.ParcelFileDescriptor command=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand("pm grant "+context.getPackageName()+" android.permission.CAMERA")) { new FileInputStream(command.getFileDescriptor()).read(new byte[256]); }
  try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)){
   scenario.onActivity(activity->{
    View root=activity.findViewById(android.R.id.content);
    assertNotNull(textView(root,"SchoolFlow Gate  ·  attended test build"));
    View confirmation=textView(root,"Confirm identity & mark");assertNotNull(confirmation);assertFalse(confirmation.isEnabled());
    View connection=textView(root,"Connection");assertNotNull(connection);connection.performClick();assertFalse(activity.isFinishing());
   });
  }
 }

 @Test public void newServerIncarnationClearsEnrollmentEvenWithSameCodeAndDevice()throws Exception {
  Vault a=new Vault(context);a.configure("FICTIONAL-TEST",1,token);a.bindScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");a.enroll(person());a.queue(event());
  assertTrue(a.bindScope("cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"));assertTrue(a.people().isEmpty());assertNull(a.pending());
 }
 @Test public void localQrReaderDecodesSyntheticSchoolFlowIdentity()throws Exception {
  assertTrue(OpenCVLoader.initLocal());FaceEngine engine=new FaceEngine(context);
  org.opencv.objdetect.QRCodeEncoder encoder=org.opencv.objdetect.QRCodeEncoder.create();
  Mat code=new Mat(),border=new Mat(),large=new Mat(),rgba=new Mat();String token="schoolflow:student:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  try{encoder.encode(token,code);Core.copyMakeBorder(code,border,4,4,4,4,Core.BORDER_CONSTANT,new Scalar(255));org.opencv.imgproc.Imgproc.resize(border,large,new Size(),8,8,org.opencv.imgproc.Imgproc.INTER_NEAREST);org.opencv.imgproc.Imgproc.cvtColor(large,rgba,org.opencv.imgproc.Imgproc.COLOR_GRAY2RGBA);assertEquals(token,engine.readQr(rgba));}finally{code.release();border.release();large.release();rgba.release();}
 }

}
