package com.schoolflow.gate;
import java.net.URI;
public final class EndpointPolicy {
 public static final String BASE="https://schoolflow-phase1.onrender.com";
 public static void validate(String base,String code,int device,String token) {
  URI url=URI.create(base);
  if(!BASE.equals(base)||!"https".equals(url.getScheme())||url.getUserInfo()!=null||url.getQuery()!=null||url.getFragment()!=null||device<=0||code==null||!code.matches("[A-Z0-9][A-Z0-9-]{2,39}")||"DEMO".equals(code)||token==null||!token.matches("[A-Za-z0-9_-]{40,60}"))throw new IllegalArgumentException("Use your private institute code, registered gate ID and connection key.");
 }
 private EndpointPolicy(){}
}
