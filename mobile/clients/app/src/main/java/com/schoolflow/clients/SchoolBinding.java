package com.schoolflow.clients;
/** Public school identity is a routing constraint, never an authentication credential. */
final class SchoolBinding {
 static boolean matches(String code,String scope,String actualCode,String actualScope){
  if(code.isEmpty()&&scope.isEmpty())return true;
  return code.matches("[A-Z0-9][A-Z0-9-]{2,39}")&&scope.matches("[0-9a-f]{32}")&&code.equals(actualCode)&&scope.equals(actualScope);
 }
 private SchoolBinding(){}
}
