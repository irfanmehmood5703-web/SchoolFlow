package com.schoolflow.clients;
import java.net.URI;
final class EndpointPolicy {
 static final String BASE="https://schoolflow-phase1.onrender.com";
 static boolean allowed(String value){
  try{URI u=new URI(value);return "https".equals(u.getScheme())&&"schoolflow-phase1.onrender.com".equals(u.getHost())&&u.getRawUserInfo()==null&&(u.getPort()==-1||u.getPort()==443);}catch(Exception e){return false;}
 }
}
