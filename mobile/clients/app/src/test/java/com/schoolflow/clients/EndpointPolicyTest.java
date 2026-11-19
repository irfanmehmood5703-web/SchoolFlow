package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
public class EndpointPolicyTest {
 @Test public void exactSecureOriginOnly(){assertTrue(EndpointPolicy.allowed("https://schoolflow-phase1.onrender.com/workspace/dashboard"));for(String url:new String[]{"http://schoolflow-phase1.onrender.com","https://schoolflow-phase1.onrender.com.evil.invalid","https://schoolflow-phase1.onrender.com@evil.invalid","https://evil.invalid@schoolflow-phase1.onrender.com","file:///data/a","javascript:alert(1)","https://schoolflow-phase1.onrender.com:444/x","https://schoolflow-phase1.onrender.com\\@evil.invalid"})assertFalse(url,EndpointPolicy.allowed(url));}
 @Test public void externalLinksNeedSafeSchemes(){
  for(String url:new String[]{"https://example.invalid/pay","tel:+923001234567","mailto:school@example.invalid"})assertTrue(url,EndpointPolicy.external(url));
  for(String url:new String[]{"javascript:alert(1)","intent://evil","file:///private","http://example.invalid","https://secret@example.invalid/pay","mailto:a@example.invalid%0d%0abcc:other@example.invalid"})assertFalse(url,EndpointPolicy.external(url));
 }
}
