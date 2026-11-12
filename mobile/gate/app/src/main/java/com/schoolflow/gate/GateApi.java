package com.schoolflow.gate;
import org.json.JSONObject;
import javax.net.ssl.HttpsURLConnection;
import java.net.URL;
import java.io.*;
import java.nio.charset.StandardCharsets;
public final class GateApi {
 public static final class Reply {public final int code;public final JSONObject json;Reply(int code,JSONObject json){this.code=code;this.json=json;}}
 public Reply post(JSONObject config,String path,JSONObject body)throws Exception {
  String base=config.getString("base"),code=config.getString("code"),token=config.getString("token");int id=config.getInt("device");
  EndpointPolicy.validate(base,code,id,token);
  if(!path.equals("heartbeat")&&!path.equals("events")&&!path.equals("identity"))throw new IllegalArgumentException("Invalid gate operation");
  HttpsURLConnection c=(HttpsURLConnection)new URL(base+"/api/attendance/devices/"+id+"/"+path).openConnection();
  c.setInstanceFollowRedirects(false);c.setConnectTimeout(10_000);c.setReadTimeout(10_000);c.setRequestMethod("POST");c.setDoOutput(true);c.setUseCaches(false);
  c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Accept","application/json");c.setRequestProperty("Authorization","Bearer "+token);c.setRequestProperty("X-Institute-Code",code);
  if(!path.equals("heartbeat")){String scope=config.getString("scope_id");if(!scope.matches("[a-f0-9]{64}"))throw new SecurityException("Verify gate identity first.");c.setRequestProperty("X-Device-Scope",scope);}
  try {
   byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);c.setFixedLengthStreamingMode(bytes.length);try(OutputStream out=c.getOutputStream()){out.write(bytes);}
   int status=c.getResponseCode();InputStream in=status>=400?c.getErrorStream():c.getInputStream();ByteArrayOutputStream result=new ByteArrayOutputStream();
   if(in!=null)try(InputStream input=in){byte[] buffer=new byte[1024];int n;while((n=input.read(buffer))!=-1){if(result.size()+n>16384)throw new IOException("Gate reply exceeds size limit.");result.write(buffer,0,n);}}
   JSONObject json;try{json=new JSONObject(result.toString(StandardCharsets.UTF_8.name()));}catch(Exception e){json=new JSONObject().put("error","Server refused the request ("+status+").");}
   return new Reply(status,json);
  } finally {c.disconnect();}
 }
}
