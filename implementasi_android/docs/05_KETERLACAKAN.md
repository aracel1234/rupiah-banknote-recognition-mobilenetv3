# Keterlacakan ke perancangan dan Bab 5

Pemetaan ini menunjukkan lokasi implementasi, bukan pernyataan lulus pengujian fungsional.

| ID kebutuhan | Pemenuhan dalam sumber |
|---|---|
| KF-01 izin kamera | `MainActivity.requestOrStart`, callback permission |
| KF-02 preview dan panduan ROI | `activity_main.xml`, `RoiOverlay`, `CameraController` |
| KF-03 akuisisi bingkai | `CameraController`, `RecognitionSession.analyze` |
| KF-04 orientasi dan crop | `YuvRoi`, `RoiGeometry`, shared ViewPort |
| KF-05 kualitas citra | `QualityGate`, `LuminanceClahe` |
| KF-06 model dan artefak | `ModelRunner`, `asset_integrity.json`, `selection_lock.json` |
| KF-07 pembentukan tensor | `FramePreprocessor`, direct ByteBuffer |
| KF-08 inferensi delapan kelas | `ModelRunner.run` |
| KF-09 pascainferensi | `TemporalDecision.accept` |
| KF-10 tahan keluaran invalid | `QualityGate`, `TemporalDecision.reject`, status UI |
| KF-11 suara nominal | `SpeechOutput.nominal`, voice Indonesia luring |
| KF-12 pengulangan suara | `TemporalDecision`, reset setelah penolakan W |
| KF-13 log teknis | `EventLog` |
| KF-14 siklus hidup/sumber daya | `MainActivity.onStop`, `RecognitionSession.close`, `finally image.close` |
| KF-15 pergantian kamera | `RecognitionSession.switchCamera`, rollback kamera, reset token/temporal |

| Kerangka laporan terbaru | Artefak yang dapat dijelaskan setelah realisasi |
|---|---|
| 5.5 Lingkungan dan struktur proyek | File Gradle, manifest, dependency, pemisahan paket |
| 5.6.1 CameraX dan ROI | CameraController, RoiGeometry, YuvRoi, RoiOverlay |
| 5.6.2 Kualitas dan praproses | QualityGate, LuminanceClahe, FramePreprocessor |
| 5.6.3 Tensor dan inferensi | ModelRunner dan aset model final |
| 5.6.4 Pascainferensi | Pemeriksaan nonuang dan threshold |
| 5.6.5 Stabilisasi temporal | Rata-rata delapan skor dalam W, minimal tiga hasil |
| 5.6.6 TTS dan status | SpeechOutput, MainActivity |
| 5.7 Parameter aplikasi | Mekanisme konfigurasi tersedia; hasil kalibrasi belum tersedia |
| 5.8 Siklus hidup | Penutupan model/worker, kamera, TTS, callback token |
| 5.9 Log dan konfigurasi lokal | JSONL terbatas dan app_config.json |
| 5.10 UI dan aksesibilitas | Tampilan satu layar, tombol sejajar, label TalkBack, suara |
| 5.11 Artefak akhir | Snapshot pengembangan tersedia; APK dan konfigurasi penelitian akhir belum dikunci |

Jangan menulis bahwa 5.7 atau 5.11 final sudah selesai hanya karena kelas konfigurasi dan snapshot telah dibuat. Paket ini tidak mengubah isi laporan pengguna.

## Rujukan API yang diperiksa

- [CameraX — transformasi keluaran](https://developer.android.com/media/camera/camerax/transform-output): buffer, crop, rotasi, dan hubungan citra analisis dengan preview.
- [CameraX — konfigurasi](https://developer.android.com/media/camera/camerax/configuration): konfigurasi use case dan ViewPort.
- [CameraX — riwayat versi](https://developer.android.com/jetpack/androidx/releases/camera): dependency CameraX yang dipin.
- [ResolutionStrategy](https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionStrategy): negosiasi resolusi dan fallback.
- [Interpreter Java](https://developers.google.com/edge/api/tflite/java/org/tensorflow/lite/Interpreter): kontrak penggunaan interpreter dan pelepasan resource.
- [TextToSpeech](https://developer.android.com/reference/android/speech/tts/TextToSpeech): inisialisasi, antrean, dan lifecycle TTS.
- [AGP 8.7](https://developer.android.com/build/releases/agp-8-7-0-release-notes): pasangan Gradle 8.9, JDK 17, dan compile SDK 35.

Dokumentasi API memberi dasar integrasi; membaca dokumentasi tidak menggantikan kompilasi atau pengamatan pada perangkat.
