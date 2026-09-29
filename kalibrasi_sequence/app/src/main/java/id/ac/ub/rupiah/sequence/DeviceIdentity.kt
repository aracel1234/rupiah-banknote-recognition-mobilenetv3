package id.ac.ub.rupiah.sequence

/**
 * Identitas perangkat penelitian yang dikunci secara statis.
 *
 * Nilai pada object ini sengaja tidak diambil dari android.os.Build agar
 * metadata, nama folder dataset, dan identitas yang ditampilkan aplikasi
 * selalu konsisten dengan Redmi 4X yang digunakan sebagai perangkat penelitian.
 */
object DeviceIdentity {
    const val ALIAS = "redmi_4x_santoni"
    const val SERIAL = "58c44e87d140"
    const val MANUFACTURER = "Xiaomi"
    const val MODEL = "Redmi 4X"
    const val DEVICE = "santoni"
    const val ANDROID_RELEASE = "7.1.2"
    const val SDK_INT = 25
    const val ABI = "arm64-v8a,armeabi-v7a,armeabi"

    val DISPLAY_TEXT: String
        get() = "$MANUFACTURER $MODEL ($DEVICE) • Android $ANDROID_RELEASE (API $SDK_INT)"
}
