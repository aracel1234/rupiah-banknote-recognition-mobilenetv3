plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "id.ac.ub.rupiah"
    compileSdk = 35
    defaultConfig {
        applicationId = "id.ac.ub.rupiah"
        minSdk = 23
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-dev"
        ndk { abiFilters += listOf("armeabi-v7a", "arm64-v8a") }
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    androidResources { noCompress += "tflite" }
    buildFeatures { buildConfig = true }
    splits { abi { isEnable = true; reset(); include("armeabi-v7a", "arm64-v8a"); isUniversalApk = true } }
}
dependencies {
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    val cameraVersion = "1.4.2"
    implementation("androidx.camera:camera-core:$cameraVersion")
    implementation("androidx.camera:camera-camera2:$cameraVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraVersion")
    implementation("androidx.camera:camera-view:$cameraVersion")
    implementation("org.tensorflow:tensorflow-lite:2.17.0")
}
