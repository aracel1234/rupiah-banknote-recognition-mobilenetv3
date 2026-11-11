# Pengenalan Nominal Rupiah — proyek Android

Proyek Android skripsi pengenalan nominal uang Rupiah berbasis MobileNetV3-Small. Model Dynamic Range hasil seleksi tetap digunakan tanpa pelatihan atau konversi ulang. Aplikasi menggunakan Kotlin, XML Views, CameraX, TensorFlow Lite lokal, dan keluaran Bahasa Indonesia luring.

**Status konfigurasi:** `operational_config_locked`, revisi `calib-operational-001`.

Kalibrasi kualitas statis Subbab 5.7.2 dan parameter pascainferensi Subbab 5.7.3 sudah dikunci. Status pascainferensi pada konfigurasi aktif adalah `calibrated_sequence_locked`. Sumber nilai operasional adalah `app/src/main/assets/app_config.json` dan bukti pada `app/src/main/assets/calibration/`.

Kode, dokumentasi, dan kontribusi model asli penulis tersedia dengan lisensi [Apache-2.0](../LICENSE), sesuai cakupan pada [README utama](../README.md#license-and-reuse). Lihat [kredit](../CREDITS.md), [sumber dataset](../DATASET_SOURCES.md), [model card](../MODEL_CARD.md), dan [panduan kontribusi](../CONTRIBUTING.md).

## Parameter yang sudah dikunci

- `roi_width_fraction = 0.90`
- `roi_aspect_ratio = 1.3420920964096548`
- `roi_height_cap_fraction = 0.90`
- `blur_variance_min = 23.74892868863396`
- `luma_min = 91.93479241966921`
- `luma_max = 178.81127789279964`
- `clahe_enabled = false`
- `yuv_range = limited_bt601`

Bukti kalibrasi yang digunakan aplikasi berada pada `app/src/main/assets/calibration/`. `AppConfig.load()` memeriksa SHA-256 lock dan kecocokan parameter sebelum sesi pengenalan dapat dimulai.

## Parameter pascainferensi operasional

Nilai berikut berasal dari konfigurasi operasional yang telah dikalibrasi:

- `analysis_fps = 3`
- `confidence_threshold = 0.65`
- `temporal_window_ms = 1500`
- `minimum_results = 3`

Stabilisasi menghitung rata-rata vektor skor dalam jendela waktu; minimum tiga hasil inferensi bukan aturan bahwa seluruh label di jendela harus identik. Model menggunakan masukan RGB float32 pada rentang [0,255], tanpa normalisasi eksternal tambahan, dan keluaran softmax float32 delapan kelas.

## Build di KDE Neon

1. Buka folder proyek yang memuat `settings.gradle.kts` melalui Android Studio.
2. Gunakan Gradle Wrapper proyek dan JDK yang sesuai dengan proyek.
3. Pastikan Android SDK Platform 35 dan komponen build yang diperlukan sudah terpasang.
4. Lakukan **Sync Project with Gradle Files**.
5. Lakukan build ulang dari sumber dan konfigurasi aktif sebelum memasang APK ke perangkat.

Build terminal:

```bash
./gradlew :app:clean :app:assembleDebug
```

APK debug berada di `app/build/outputs/apk/debug/`. Proyek menyertakan target `armeabi-v7a`, `arm64-v8a`, dan APK universal.

Pemasangan contoh:

```bash
adb devices
adb install -r app/build/outputs/apk/debug/app-universal-debug.apk
```

Jika beberapa perangkat terhubung, gunakan `adb -s SERIAL`.

## Alur kualitas setelah 5.7.2

Urutan keputusan kualitas tetap mengikuti rancangan dan implementasi yang sudah ditulis sampai Subbab 5.6:

1. ambil luminansi Y pada ROI;
2. CLAHE hanya dapat diterapkan secara bersyarat apabila konfigurasi mengaktifkannya;
3. periksa kelayakan pencahayaan;
4. periksa ketajaman dengan Varians Laplacian;
5. ROI yang lolos dikonversi ke RGB, diubah menjadi 224 × 224 dengan bilinear, lalu diteruskan ke model.

Hasil kalibrasi 5.7.2 memilih **tanpa CLAHE**, sehingga jalur operasional saat ini menggunakan luminansi Y asli untuk gerbang pencahayaan dan ketajaman.

## Keterlacakan konfigurasi 5.6 dan 5.7.2

Konfigurasi pengembangan yang didokumentasikan pada Subbab 5.6 disimpan sebagai `docs/config_history/app_config_5_6_development.json`. Berkas operasional saat ini adalah `app/src/main/assets/app_config.json` dan telah diperbarui menggunakan hasil 5.7.2. Dengan demikian, nilai pengembangan pada uraian 5.6 tetap dapat ditelusuri tanpa mengembalikan aplikasi ke konfigurasi lama.

## Catatan penggunaan

Kamera belakang menjadi kamera awal. Pergantian kamera mengosongkan riwayat keputusan. Aplikasi menahan ROI yang tidak memenuhi kualitas, kelas nonuang, prediksi di bawah ambang, atau prediksi yang belum stabil. Nominal yang sudah diterima tidak diucapkan berulang pada setiap bingkai. Perilaku pascainferensi mengikuti konfigurasi operasional yang telah dikunci.

Pertahankan parameter dan bukti konfigurasi ini sebagai acuan penelitian. Pengembangan komunitas yang mengubah model, prapemrosesan, atau parameter keputusan perlu memiliki revisi dan hasil pengujian tersendiri.

Inferensi berlangsung lokal. Saat memakai jalur TTS aplikasi, pasang terlebih dahulu suara Bahasa Indonesia luring. Uji jalur TalkBack secara terpisah. Evaluasi skripsi merupakan evaluasi teknis; pengujian kemudahan penggunaan langsung bersama pengguna tunanetra masih menjadi tahap kolaborasi berikutnya.

Untuk rilis baru, gunakan kunci signing privat di luar repo dan sertakan pemberitahuan lisensi/atribusi. Keystore benchmark yang pernah masuk riwayat publik tidak digunakan sebagai kunci rilis komunitas baru. Penghapusan dari branch aktif tidak menghapus salinan pada riwayat Git.
