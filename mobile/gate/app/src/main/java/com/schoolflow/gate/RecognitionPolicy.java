package com.schoolflow.gate;
import java.util.*;
/** Conservative open-set matching; not a liveness or identity proof. */
public final class RecognitionPolicy {
 public static final int DIMENSIONS=128;
 public static final double THRESHOLD=0.55, MARGIN=0.08;
 public static final class Identity {
  public final String kind,label,qrToken,binding; public final int id; public final List<float[]> samples;
  public Identity(String kind,int id,String label,String qrToken,String binding,List<float[]> samples) {
   if(!("student".equals(kind)||"staff".equals(kind)) || id<=0 || label==null || label.trim().isEmpty() || label.length()>120 || samples==null || samples.size()<1 || samples.size()>3) throw new IllegalArgumentException("Invalid enrollment");
   String type=kind.equals("student")?"student":"employee";
   if(qrToken==null||!qrToken.matches("schoolflow:"+type+":[a-f0-9]{64}")||binding==null||!binding.matches("[A-Za-z0-9_-]{43}"))throw new IllegalArgumentException("Verify the SchoolFlow identity QR first.");
   ArrayList<float[]> copy=new ArrayList<>();
   for(float[] v:samples) { validate(v); copy.add(v.clone()); }
   this.kind=kind;this.id=id;this.label=label;this.qrToken=qrToken;this.binding=binding;this.samples=Collections.unmodifiableList(copy);
  }
  public String key(){return kind+":"+id;}
 }
 public static final class Match {
  public final Identity identity;public final double score;
  Match(Identity identity,double score){this.identity=identity;this.score=score;}
 }
 public static void validate(float[] vector) {
  if(vector==null||vector.length!=DIMENSIONS)throw new IllegalArgumentException("Invalid face feature");
  double norm=0;for(float x:vector){if(!Float.isFinite(x))throw new IllegalArgumentException("Invalid face feature");norm+=(double)x*x;}
  if(!Double.isFinite(norm)||norm<1e-12)throw new IllegalArgumentException("Invalid face feature");
 }
 public static double cosine(float[] a,float[] b) {
  validate(a);validate(b);double dot=0,aa=0,bb=0;
  for(int i=0;i<DIMENSIONS;i++){dot+=(double)a[i]*b[i];aa+=(double)a[i]*a[i];bb+=(double)b[i]*b[i];}
  return dot/Math.sqrt(aa*bb);
 }
 public static Match match(float[] feature,List<Identity> people) {
  validate(feature);Identity best=null;double first=-2,second=-2;
  HashSet<String> keys=new HashSet<>();
  for(Identity p:people) {
   if(!keys.add(p.key()))throw new IllegalArgumentException("Duplicate identity");
   double score=-2;for(float[] sample:p.samples)score=Math.max(score,cosine(feature,sample));
   if(score>first){second=first;first=score;best=p;}else second=Math.max(second,score);
  }
  return best!=null&&first>=THRESHOLD&&first-second>=MARGIN?new Match(best,first):null;
 }
 public static final class Stable {
  private String key="";private int count;private long first,last;
  public synchronized boolean observe(String candidate,long clock) {
   if(candidate==null||candidate.isEmpty()){reset();return false;}
   if(!candidate.equals(key)||clock<last||clock-last>1500){key=candidate;count=1;first=clock;}else count++;
   last=clock;return count>=3&&clock-first>=1000;
  }
  public synchronized void reset(){key="";count=0;first=0;last=0;}
 }
 private RecognitionPolicy(){}
}
