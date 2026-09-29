# Patch Android setelah kalibrasi statis 5.7.2

Patch ini dibuat dari `implementasi_android(3).zip` yang dikirim pengguna.
Semua berkas kode pada patch disediakan dalam bentuk lengkap, bukan fragmen.

## Tujuan

- Mengunci hasil 5.7.2 pada aplikasi utama.
- Mempertahankan urutan kualitas sesuai skripsi terbaru: CLAHE bersyarat -> pencahayaan -> ketajaman.
- Menonaktifkan CLAHE karena hasil Stage 7 tidak memenuhi kriteria seleksi.
- Menjaga parameter 5.7.3 tetap sementara agar pengumpulan/analisis sequence tidak tercampur dengan hasil 5.7.2.
- Menambahkan verifikasi SHA-256 bukti konfigurasi statis saat aplikasi memuat konfigurasi.

## Parameter statis terkunci

- roi_width_fraction = 0.90
- roi_aspect_ratio = 1.3420920964096548
- roi_height_cap_fraction = 0.90
- blur_variance_min = 23.74892868863396
- luma_min = 91.93479241966921
- luma_max = 178.81127789279964
- clahe_enabled = false
- yuv_range = limited_bt601

## Parameter yang sengaja TIDAK difinalkan

- analysis_fps = 3
- confidence_threshold = 0.80
- temporal_window_ms = 1500
- minimum_results = 3

Nilai di atas tetap nilai pengembangan sampai 5.7.3 selesai.

## Berkas berubah / ditambah

- CHANGED: `README.md`
- CHANGED: `app/src/main/assets/app_config.json`
- ADDED: `app/src/main/assets/calibration/static_quality_config.json`
- ADDED: `app/src/main/assets/calibration/static_quality_config_lock.json`
- CHANGED: `app/src/main/java/id/ac/ub/rupiah/config/AppConfig.kt`
- CHANGED: `app/src/main/java/id/ac/ub/rupiah/image/FramePreprocessor.kt`
- CHANGED: `app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt`
- CHANGED: `app/src/main/java/id/ac/ub/rupiah/image/RoiGeometry.kt`
- CHANGED: `app/src/main/java/id/ac/ub/rupiah/session/RecognitionSession.kt`
- CHANGED: `docs/02_ARSITEKTUR_DAN_ALUR.md`
- CHANGED: `docs/03_TAHAP_LANJUTAN.md`
- CHANGED: `docs/04_KONFIGURASI_DAN_BATASAN.md`
- CHANGED: `docs/05_KETERLACAKAN.md`
- CHANGED: `docs/06_PEMERIKSAAN_TEKNIS.md`
- ADDED: `docs/config_history/README.md`
- ADDED: `docs/config_history/app_config_5_6_development.json`
- CHANGED: `docs/implementation_snapshot.json`

## Penerapan

Ekstrak isi ZIP patch ke root `/home/aracel/Downloads/Skripsi/implementasi_android` dengan overwrite.
Kemudian jalankan:

```bash
cd /home/aracel/Downloads/Skripsi/implementasi_android
./gradlew :app:clean :app:assembleDebug
```

Patch ini tidak mengubah model `.tflite`, `ModelRunner.kt`, `TemporalDecision.kt`, `SpeechOutput.kt`, `CameraController.kt`, `MainActivity.kt`, atau Sequence Collector.
