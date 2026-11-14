package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
public class PortalPermissionsTest {
 @Test public void onlyForegroundTrustedAudioIsAllowed(){assertTrue(PortalPermissions.microphone(EndpointPolicy.BASE,EndpointPolicy.BASE+"/workspace/conversations",new String[]{PortalPermissions.AUDIO},true));}
 @Test public void cameraAndCombinedRequestsAreRefused(){for(String[] resources:new String[][]{null,new String[]{},new String[]{"android.webkit.resource.VIDEO_CAPTURE"},new String[]{PortalPermissions.AUDIO,"android.webkit.resource.VIDEO_CAPTURE"}})assertFalse(PortalPermissions.microphone(EndpointPolicy.BASE,EndpointPolicy.BASE,resources,true));}
 @Test public void foreignAndSpoofedOriginsCannotObtainMicrophone(){for(String url:new String[]{"https://evil.invalid","http://schoolflow-phase1.onrender.com","https://schoolflow-phase1.onrender.com.evil.invalid","https://evil.invalid@schoolflow-phase1.onrender.com","https://schoolflow-phase1.onrender.com:444"}){assertFalse(PortalPermissions.microphone(url,EndpointPolicy.BASE,new String[]{PortalPermissions.AUDIO},true));assertFalse(PortalPermissions.microphone(EndpointPolicy.BASE,url,new String[]{PortalPermissions.AUDIO},true));}}
 @Test public void backgroundAndMissingPagesAreRefused(){assertFalse(PortalPermissions.microphone(EndpointPolicy.BASE,EndpointPolicy.BASE,new String[]{PortalPermissions.AUDIO},false));assertFalse(PortalPermissions.microphone(EndpointPolicy.BASE,null,new String[]{PortalPermissions.AUDIO},true));}
}
