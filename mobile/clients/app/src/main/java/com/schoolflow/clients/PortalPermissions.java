package com.schoolflow.clients;
final class PortalPermissions {
 static final String AUDIO="android.webkit.resource.AUDIO_CAPTURE";
 static boolean microphone(String origin,String page,String[] resources,boolean foreground){
  return foreground&&EndpointPolicy.allowed(origin)&&EndpointPolicy.allowed(page)&&resources!=null&&resources.length==1&&AUDIO.equals(resources[0]);
 }
 static boolean location(String role,String origin,String page,boolean foreground){return "teacher".equals(role)&&foreground&&EndpointPolicy.allowed(origin)&&EndpointPolicy.allowed(page);}
 private PortalPermissions(){}
}
