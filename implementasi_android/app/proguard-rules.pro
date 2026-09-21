# TensorFlow Lite ships consumer rules; JNI classes are kept explicitly too.
-keep class org.tensorflow.lite.** { *; }
-keep class id.ac.ub.rupiah.ui.RoiOverlay { public <init>(...); }
