package com.schoolflow.clients;
import java.net.URI;
final class EndpointPolicy {
 static final String BASE="https://schoolflow-phase1.onrender.com";
 static boolean allowed(String value){
  try{URI u=new URI(value);return "https".equals(u.getScheme())&&"schoolflow-phase1.onrender.com".equals(u.getHost())&&u.getRawUserInfo()==null&&(u.getPort()==-1||u.getPort()==443);}catch(Exception e){return false;}
 }
 static boolean external(String value){
  try{URI u=new URI(value);
   if("https".equals(u.getScheme()))return u.getHost()!=null&&u.getRawUserInfo()==null&&(u.getPort()==-1||u.getPort()==443);
   if("tel".equals(u.getScheme()))return u.getSchemeSpecificPart().matches("[+0-9().-]{3,30}");
   if("mailto".equals(u.getScheme()))return u.getSchemeSpecificPart().matches("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}");
  }catch(Exception e){return false;}
  return false;
 }
}
