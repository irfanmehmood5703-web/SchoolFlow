package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
public class EndpointPolicyTest {
 @Test public void exactSecureOriginOnly(){assertTrue(EndpointPolicy.allowed("https://schoolflow-phase1.onrender.com/workspace/dashboard"));for(String url:new String[]{"http://schoolflow-phase1.onrender.com","https://schoolflow-phase1.onrender.com.evil.invalid","https://schoolflow-phase1.onrender.com@evil.invalid","https://evil.invalid@schoolflow-phase1.onrender.com","file:///data/a","javascript:alert(1)","https://schoolflow-phase1.onrender.com:444/x","https://schoolflow-phase1.onrender.com\\@evil.invalid"})assertFalse(url,EndpointPolicy.allowed(url));}
}
