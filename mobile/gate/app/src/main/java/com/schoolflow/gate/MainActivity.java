package com.schoolflow.gate;
import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
public class MainActivity extends Activity {
 @Override public void onCreate(Bundle saved) { super.onCreate(saved); TextView label=new TextView(this); label.setText("SchoolFlow Gate — build verification"); setContentView(label); }
}
