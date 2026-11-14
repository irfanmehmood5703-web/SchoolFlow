package com.schoolflow.clients;
final class PortalPermissions {
 static final String AUDIO="android.webkit.resource.AUDIO_CAPTURE";
 static boolean microphone(String origin,String page,String[] resources,boolean foreground){
  return foreground&&EndpointPolicy.allowed(origin)&&EndpointPolicy.allowed(page)&&resources!=null&&resources.length==1&&AUDIO.equals(resources[0]);
 }
 private PortalPermissions(){}
}
