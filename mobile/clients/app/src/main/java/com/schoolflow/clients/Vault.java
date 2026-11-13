package com.schoolflow.clients;
import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.security.KeyStore;
import java.nio.file.*;
import java.nio.ByteBuffer;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
final class Vault {
 private final Context context;Vault(Context c){context=c;}
 private javax.crypto.SecretKey key() throws Exception {String alias="schoolflow-client-v1";KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);if(!ks.containsAlias(alias)){KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");gen.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());gen.generateKey();}return (javax.crypto.SecretKey)ks.getKey(alias,null);}
 synchronized String read() throws Exception {Path path=context.getNoBackupFilesDir().toPath().resolve("connection.enc");if(!Files.exists(path))return "{}";byte[] bytes=Files.readAllBytes(path);if(bytes.length<29)throw new Exception("Invalid private storage");ByteBuffer b=ByteBuffer.wrap(bytes);byte[] iv=new byte[12];b.get(iv);byte[] data=new byte[b.remaining()];b.get(data);Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,iv));return new String(c.doFinal(data),java.nio.charset.StandardCharsets.UTF_8);}
 synchronized void save(String value) throws Exception {Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key());byte[] data=c.doFinal(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));byte[] bytes=ByteBuffer.allocate(12+data.length).put(c.getIV()).put(data).array();Path root=context.getNoBackupFilesDir().toPath();Path tmp=root.resolve("connection.tmp");Files.write(tmp,bytes);Files.move(tmp,root.resolve("connection.enc"),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}
}
