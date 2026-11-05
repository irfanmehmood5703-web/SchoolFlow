package com.schoolflow.gate;
import android.content.Context;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;
import org.opencv.core.*;
import org.opencv.imgproc.Imgproc;
import org.opencv.objdetect.FaceDetectorYN;
import org.opencv.objdetect.FaceRecognizerSF;
/** Local YuNet/SFace inference. No camera frame is persisted or transmitted. */
public final class FaceEngine {
 private final FaceDetectorYN detector;private final FaceRecognizerSF recognizer;
 public FaceEngine(Context context)throws Exception {
  String detectorPath=asset(context,"face_detection_yunet_2023mar.onnx","8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4");
  String recognizerPath=asset(context,"face_recognition_sface_2021dec.onnx","0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79");
  detector=FaceDetectorYN.create(detectorPath,"",new Size(320,320),0.9f,0.3f,5000);
  recognizer=FaceRecognizerSF.create(recognizerPath,"");
 }
 private static String asset(Context context,String name,String hash)throws Exception {
  File file=new File(context.getNoBackupFilesDir(),name);
  if(!file.exists()||!sha(file).equals(hash)){
   File temporary=new File(context.getNoBackupFilesDir(),name+".tmp");
   try(InputStream in=context.getAssets().open(name);OutputStream out=new FileOutputStream(temporary)){byte[] b=new byte[16384];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
   if(!sha(temporary).equals(hash)){temporary.delete();throw new SecurityException("Model verification failed.");}
   if(file.exists()&&!file.delete())throw new IOException("Cannot replace model.");
   if(!temporary.renameTo(file))throw new IOException("Cannot install model.");
  }
  return file.getAbsolutePath();
 }
 private static String sha(File file)throws Exception {
  MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[16384];int n;while((n=in.read(b))!=-1)digest.update(b,0,n);}
  StringBuilder hex=new StringBuilder();for(byte x:digest.digest())hex.append(String.format(Locale.ROOT,"%02x",x&255));return hex.toString();
 }
 /** Exercises native feature inference with synthetic pixels, not a face-accuracy test. */
 synchronized int runtimeFeatureShape() {
  Mat sample=new Mat(112,112,CvType.CV_8UC3,new Scalar(127,127,127)),out=new Mat();
  try{recognizer.feature(sample,out);return (int)out.total();}finally{sample.release();out.release();}
 }
 public synchronized float[] extract(Mat rgba) {
  Mat bgr=new Mat(),faces=new Mat(),aligned=new Mat(),feature=new Mat(),face=null;
  try {
   Imgproc.cvtColor(rgba,bgr,Imgproc.COLOR_RGBA2BGR);detector.setInputSize(bgr.size());detector.detect(bgr,faces);
   if(faces.rows()!=1)return null;
   float[] bounds=new float[15];faces.get(0,0,bounds);
   if(bounds[2]<90||bounds[3]<90||bounds[14]<0.9)return null;
   face=faces.row(0);recognizer.alignCrop(bgr,face,aligned);recognizer.feature(aligned,feature);
   if(feature.total()!=RecognitionPolicy.DIMENSIONS)return null;
   float[] vector=new float[RecognitionPolicy.DIMENSIONS];feature.get(0,0,vector);RecognitionPolicy.validate(vector);return vector;
  }finally{if(face!=null)face.release();bgr.release();faces.release();aligned.release();feature.release();}
 }
}
