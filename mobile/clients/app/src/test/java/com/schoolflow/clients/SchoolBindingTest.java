package com.schoolflow.clients;
import org.junit.Test;
import static org.junit.Assert.*;
public class SchoolBindingTest {
 @Test public void schoolPackagesCannotConnectElsewhere(){
  String scope="0123456789abcdef0123456789abcdef";
  assertTrue(SchoolBinding.matches("QA-SCHOOL",scope,"QA-SCHOOL",scope));
  assertFalse(SchoolBinding.matches("QA-SCHOOL",scope,"OTHER-SCHOOL",scope));
  assertFalse(SchoolBinding.matches("QA-SCHOOL",scope,"QA-SCHOOL","different"));
  assertFalse(SchoolBinding.matches("QA-SCHOOL",scope,"QA-SCHOOL",""));
  assertTrue(SchoolBinding.matches("","","ANY-SCHOOL",scope));
 }
}
