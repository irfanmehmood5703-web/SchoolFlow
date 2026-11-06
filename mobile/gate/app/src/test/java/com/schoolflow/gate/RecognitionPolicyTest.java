package com.schoolflow.gate;
import org.junit.Test;
import java.util.*;
import static org.junit.Assert.*;
public class RecognitionPolicyTest {
 private float[] axis(int n){float[] v=new float[128];v[n]=1;return v;}
 private RecognitionPolicy.Identity person(int id,float[] v){return new RecognitionPolicy.Identity("student",id,"Fictional pupil "+id,"schoolflow:student:"+String.format(Locale.ROOT,"%064x",id),"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Collections.singletonList(v));}
 @Test public void knownFaceHasClearMargin(){RecognitionPolicy.Match m=RecognitionPolicy.match(axis(0),Arrays.asList(person(1,axis(0)),person(2,axis(1))));assertNotNull(m);assertEquals(1,m.identity.id);}
 @Test public void unknownFaceDoesNotDefaultToFirstEnrollment(){assertNull(RecognitionPolicy.match(axis(2),Arrays.asList(person(1,axis(0)),person(2,axis(1)))));}
 @Test public void ambiguousMatchIsRefused(){assertNull(RecognitionPolicy.match(axis(0),Arrays.asList(person(1,axis(0)),person(2,axis(0)))));}
 @Test public void ambiguousRecognitionCannotPermitDuplicateEnrollment(){
  List<RecognitionPolicy.Identity> existing=Arrays.asList(person(1,axis(0)),person(2,axis(0)));
  assertNull(RecognitionPolicy.match(axis(0),existing));
  assertNotNull(RecognitionPolicy.enrollmentConflict(person(3,axis(0)),existing));
 }
 @Test public void enrollmentChecksEveryNewAndExistingSample(){
  RecognitionPolicy.Identity incoming=new RecognitionPolicy.Identity("student",3,"Fictional pupil 3",String.format(Locale.ROOT,"schoolflow:student:%064x",3),"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Arrays.asList(axis(2),axis(1),axis(3)));
  RecognitionPolicy.Identity existing=new RecognitionPolicy.Identity("student",1,"Fictional pupil 1",String.format(Locale.ROOT,"schoolflow:student:%064x",1),"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Arrays.asList(axis(0),axis(1)));
  assertNull(RecognitionPolicy.match(incoming.samples.get(0),Collections.singletonList(existing)));
  assertEquals(1,RecognitionPolicy.enrollmentConflict(incoming,Collections.singletonList(existing)).id);
 }
 @Test public void distinctEnrollmentAndSameIdentityReplacementAreAllowed(){
  assertNull(RecognitionPolicy.enrollmentConflict(person(3,axis(2)),Arrays.asList(person(1,axis(0)),person(2,axis(1)))));
  assertNull(RecognitionPolicy.enrollmentConflict(person(1,axis(0)),Collections.singletonList(person(1,axis(0)))));
 }
 @Test public void noEnrollmentHasNoMatch(){assertNull(RecognitionPolicy.match(axis(0),Collections.emptyList()));}
 @Test(expected=IllegalArgumentException.class) public void zeroFeaturesRefused(){RecognitionPolicy.match(new float[128],Collections.emptyList());}
 @Test(expected=IllegalArgumentException.class) public void nanRefused(){float[] v=axis(0);v[1]=Float.NaN;RecognitionPolicy.validate(v);}
 @Test(expected=IllegalArgumentException.class) public void wrongDimensionRefused(){RecognitionPolicy.validate(new float[127]);}
 @Test(expected=IllegalArgumentException.class) public void invalidIdentityRefused(){new RecognitionPolicy.Identity("owner",1,"Fictional","schoolflow:student:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",Collections.singletonList(axis(0)));}
 @Test(expected=IllegalArgumentException.class) public void duplicateIdentityCannotHideAmbiguity(){RecognitionPolicy.match(axis(0),Arrays.asList(person(1,axis(0)),person(1,axis(1))));}
 @Test public void stableCandidateNeedsThreeFramesAndTime(){RecognitionPolicy.Stable s=new RecognitionPolicy.Stable();assertFalse(s.observe("student:1",100));assertFalse(s.observe("student:1",600));assertTrue(s.observe("student:1",1100));assertFalse(s.observe(null,1200));assertFalse(s.observe("student:1",1300));}
 @Test public void changedFaceAndLongGapsResetStability(){RecognitionPolicy.Stable s=new RecognitionPolicy.Stable();s.observe("student:1",100);s.observe("student:1",600);assertFalse(s.observe("student:2",1100));assertFalse(s.observe("student:2",3000));}
 @Test public void encryptedCopyDoesNotShareMutableInput(){float[] v=axis(0);RecognitionPolicy.Identity p=person(1,v);v[0]=0;assertEquals(1.0,p.samples.get(0)[0],0);}
 @Test public void gateEndpointIsExactPrivateHttps(){EndpointPolicy.validate(EndpointPolicy.BASE,"FICTIONAL-TEST",1,"FictionalGateKey_123456789012345678901234567890");}
 @Test(expected=IllegalArgumentException.class) public void foreignHostRefused(){EndpointPolicy.validate("https://schoolflow-phase1.onrender.com.evil.invalid","TEST",1,"FictionalGateKey_123456789012345678901234567890");}
 @Test(expected=IllegalArgumentException.class) public void demoCannotConnect(){EndpointPolicy.validate(EndpointPolicy.BASE,"DEMO",1,"FictionalGateKey_123456789012345678901234567890");}
}
