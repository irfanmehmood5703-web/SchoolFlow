package com.schoolflow.gate;
import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.*;
import java.security.KeyStore;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.json.*;
/** AES-GCM authenticated data in app-private, backup-excluded storage. */
public final class Vault {
 private static final String ALIAS="schoolflow.gate.v1";
 private final AtomicFile file;private final SecretKey key;private JSONObject root;
 public Vault(Context context)throws Exception {
  file=new AtomicFile(new File(context.getNoBackupFilesDir(),"gate.vault"));
  KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
  if(ks.containsAlias(ALIAS))key=(SecretKey)ks.getKey(ALIAS,null);
  else {
   if(file.getBaseFile().exists())throw new SecurityException("Protected storage key is missing.");
   KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
   generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setRandomizedEncryptionRequired(true).build());
   key=generator.generateKey();
  }
  root=new JSONObject();
  if(file.getBaseFile().exists()){
   byte[] bytes=file.readFully();if(bytes.length<29||bytes.length>4_100_000)throw new SecurityException("Protected storage is invalid.");
   byte[] iv=Arrays.copyOfRange(bytes,0,12),ciphertext=Arrays.copyOfRange(bytes,12,bytes.length);
   Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key,new GCMParameterSpec(128,iv));
   root=new JSONObject(new String(cipher.doFinal(ciphertext),java.nio.charset.StandardCharsets.UTF_8));
  }
 }
 private void persist(JSONObject next)throws Exception {
  byte[] plain=next.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
  if(plain.length>4_000_000)throw new IllegalArgumentException("Local enrollment limit reached.");
  Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key);
  byte[] encrypted=cipher.doFinal(plain);FileOutputStream out=null;
  try {out=file.startWrite();out.write(cipher.getIV());out.write(encrypted);file.finishWrite(out);root=next;}
  catch(Exception e){if(out!=null)file.failWrite(out);throw e;}
 }
 private JSONObject copy()throws JSONException{return new JSONObject(root.toString());}
 public synchronized JSONObject config()throws JSONException {JSONObject c=root.optJSONObject("config");return c==null?null:new JSONObject(c.toString());}
 public synchronized boolean scopeChanged(String code,int device) {
  JSONObject old=root.optJSONObject("config");return old!=null&&(!old.optString("code").equals(code)||old.optInt("device")!=device);
 }
 public synchronized void configure(String code,int device,String token)throws Exception {
  EndpointPolicy.validate(EndpointPolicy.BASE,code,device,token);JSONObject next=copy();
  if(scopeChanged(code,device)){next.remove("people");next.remove("pending");next.remove("last_result");}
  JSONObject config=new JSONObject().put("base",EndpointPolicy.BASE).put("code",code).put("device",device).put("token",token);
  JSONObject previous=root.optJSONObject("config");
  if(previous!=null&&!scopeChanged(code,device)&&previous.has("scope_id"))config.put("scope_id",previous.getString("scope_id"));
  next.put("config",config);persist(next);
 }
 public synchronized boolean bindScope(String scope)throws Exception {
  if(scope==null||!scope.matches("[a-f0-9]{64}"))throw new SecurityException("Gate identity could not be verified.");
  JSONObject config=root.optJSONObject("config");if(config==null)throw new SecurityException("Connect the gate first.");
  String old=config.optString("scope_id","");
  if(scope.equals(old))return false;
  JSONObject next=copy();boolean changed=!old.isEmpty()||root.has("people")||root.has("pending");
  if(changed){next.remove("people");next.remove("pending");next.put("last_result","School/gate identity changed. Old enrollment and pending submission were cleared; verify previous web history.");}
  next.getJSONObject("config").put("scope_id",scope);persist(next);return changed;
 }
 public synchronized List<RecognitionPolicy.Identity> people()throws JSONException {
  JSONArray rows=root.optJSONArray("people");ArrayList<RecognitionPolicy.Identity> people=new ArrayList<>();
  if(rows!=null)for(int i=0;i<rows.length();i++){
   JSONObject row=rows.getJSONObject(i);JSONArray samples=row.getJSONArray("samples");ArrayList<float[]> features=new ArrayList<>();
   for(int j=0;j<samples.length();j++){JSONArray vector=samples.getJSONArray(j);float[] v=new float[vector.length()];for(int k=0;k<v.length;k++)v[k]=(float)vector.getDouble(k);features.add(v);}
   people.add(new RecognitionPolicy.Identity(row.getString("kind"),row.getInt("id"),row.getString("label"),row.getString("qr_token"),row.getString("identity_binding"),features));
  }
  return people;
 }
 public synchronized void enroll(RecognitionPolicy.Identity identity)throws Exception {
  if(root.optJSONObject("config")==null||!root.getJSONObject("config").optString("scope_id","").matches("[a-f0-9]{64}"))throw new IllegalStateException("Verify the gate connection first.");
  ArrayList<RecognitionPolicy.Identity> people=new ArrayList<>(people());people.removeIf(p->p.key().equals(identity.key()));
  if(people.size()>=500)throw new IllegalArgumentException("This test build supports up to 500 local identities.");
  people.add(identity);JSONArray rows=new JSONArray();
  for(RecognitionPolicy.Identity p:people){JSONArray samples=new JSONArray();for(float[] v:p.samples){JSONArray a=new JSONArray();for(float x:v)a.put(x);samples.put(a);}rows.put(new JSONObject().put("kind",p.kind).put("id",p.id).put("label",p.label).put("qr_token",p.qrToken).put("identity_binding",p.binding).put("samples",samples).put("enrolled_at",java.time.Instant.now().toString()).put("permission_attested",true));}
  JSONObject next=copy();next.put("people",rows);persist(next);
 }
 public synchronized void remove(String identity)throws Exception {
  JSONArray old=root.optJSONArray("people"),rows=new JSONArray();
  if(old!=null)for(int i=0;i<old.length();i++){JSONObject row=old.getJSONObject(i);if(!(row.getString("kind")+":"+row.getInt("id")).equals(identity))rows.put(row);}
  JSONObject next=copy();next.put("people",rows);persist(next);
 }
 public synchronized JSONObject pending()throws JSONException {JSONObject p=root.optJSONObject("pending");return p==null?null:new JSONObject(p.toString());}
 public synchronized void queue(JSONObject body)throws Exception {
  if(root.optJSONObject("pending")!=null)throw new IllegalStateException("Resolve the pending submission first.");
  String scope=root.getJSONObject("config").getString("scope_id");if(!scope.matches("[a-f0-9]{64}"))throw new IllegalStateException("Verify the gate first.");
  JSONObject next=copy();next.put("pending",new JSONObject().put("body",body).put("scope_id",scope).put("captured_ms",System.currentTimeMillis()));persist(next);
 }
 public synchronized void finish(String eventId,String message)throws Exception {
  JSONObject pending=root.optJSONObject("pending");
  if(pending==null||!pending.getJSONObject("body").getString("event_id").equals(eventId))return;
  JSONObject next=copy();next.remove("pending");next.put("last_result",message);persist(next);
 }
 public synchronized String lastResult(){return root.optString("last_result","No attendance submitted from this device.");}
}
