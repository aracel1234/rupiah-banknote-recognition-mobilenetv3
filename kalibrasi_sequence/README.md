# Rupiah Sequence Collector

Aplikasi Android **terpisah** untuk mengumpulkan 40 urutan kalibrasi temporal per perangkat pada penelitian pengenalan nominal Rupiah. Project ini dibuat khusus untuk Subbab 5.7.3 dan tidak menggantikan `RupiahCalibrationCollector_v3` yang mengumpulkan 360 citra statis per perangkat.

## Dasar rancangan

Komposisi per perangkat mengikuti rancangan skripsi:

- 28 urutan nominal = 7 nominal × 4 skenario: stabil, gerakan ringan, perubahan jarak, perubahan orientasi;
- 6 urutan nonuang;
- 6 urutan pergantian objek;
- total 40 urutan per perangkat, 80 urutan untuk POCO X5 Pro 5G + Xiaomi Redmi 4X.

Setiap urutan berdurasi 12 detik dan memiliki cue/stage terjadwal. Aplikasi mengumpulkan stream pada target **5 FPS** agar data yang sama dapat diputar ulang secara offline untuk kandidat 5 FPS atau didownsample ke 3 FPS. Aplikasi tidak memilih threshold/window final di Android.

## Penting: jalankan setelah hasil 5.7.2 tersedia

Sebelum tombol `Mulai sequence` dapat dipakai, aplikasi mewajibkan konfirmasi konfigurasi hasil 5.7.2:

- `roi_width_fraction` 0.70 / 0.80 / 0.90;
- `blur_variance_min`;
- `luma_min`;
- `luma_max`;
- CLAHE aktif/tidak;
- `clahe_clip_limit`;
- `clahe_grid`.

Setelah sequence pertama tersimpan, konfigurasi dikunci untuk dataset perangkat tersebut. Ini mencegah 40 sequence tercampur dengan preprocessing yang berbeda.

## Kesetaraan dengan pipeline skripsi

Aplikasi memakai artefak model **yang sama** dengan aplikasi utama:

- kandidat: `dynamic_range`;
- SHA-256 model: `fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676`;
- input `[1,224,224,3]` `float32`;
- output `[1,8]` `float32`;
- kelas: `1000, 2000, 5000, 10000, 20000, 50000, 100000, nonuang`;
- TensorFlow Lite 2.17.0, CPU XNNPACK, 4 thread;
- YUV `limited_bt601` → RGB;
- resize bilinear half-pixel tanpa antialias;
- ROI terpusat dengan rasio aspek `1.3420920964096548`;
- urutan pemeriksaan kualitas sama: CLAHE kondisional → pencahayaan → blur → inferensi.

Frame yang gagal quality gate tetap dicatat ke `frames.csv`, tetapi tidak menjalankan inferensi, sama seperti pipeline aplikasi utama. Ini penting karena penolakan kualitas mengosongkan bukti temporal dalam simulasi offline.

## Apa yang disimpan

Untuk setiap sequence:

- `frames.csv`: timestamp, stage, ground-truth stage, quality metrics, 8 skor model, top-1, timing preprocessing/inferensi/pipeline;
- `stages.json`: jadwal cue dan label yang diharapkan;
- `config_snapshot.json`: konfigurasi 5.7.2 yang dipakai;
- `metadata.json`: perangkat, hash model, hash konfigurasi, jumlah frame, median/p95 pipeline, status kapasitas 5 FPS.

Pada root perangkat:

- `experiment_plan.json`;
- `collector_config.json`;
- `checklist.json` / `checklist.csv`;
- `manifest.jsonl` / `manifest.csv`.

## Google Drive

Penyimpanan menggunakan mekanisme yang sama dengan collector citra statis, yaitu Android **Storage Access Framework** tanpa credential OAuth di APK.

1. Tekan `Pilih folder Drive`.
2. Pilih folder Google Drive tujuan.
3. Data selalu disimpan lokal terlebih dahulu.
4. Setelah sequence selesai, empat file sequence disinkronkan ke Drive.
5. Manifest/checklist disinkronkan setelah status lokal final.
6. Jika Drive gagal/offline, sequence lokal tetap aman dan dapat disinkronkan ulang dengan tombol `Sinkronkan`.

Root cloud yang dibuat adalah `RupiahSequenceCollector/<device_alias>/...`, sehingga **tidak menimpa** `RupiahCalibrationCollector` yang berisi 360 citra statis.

## Kondisi kendali sequence

Agar kalibrasi pascainferensi tidak sekaligus menjadi eksperimen pencahayaan, seluruh sequence dijalankan pada **pencahayaan normal 350–450 lux**, kamera belakang, objek tajam, dan posisi awal sekitar **20 cm**, kecuali skenario `DISTANCE` yang memang mengubah jarak. Kamera dibiarkan memakai perilaku AE/AWB/AF otomatis seperti aplikasi operasional; kontrol manual pada collector citra statis tidak dipakai di sini karena tujuan sequence adalah merekam perilaku pipeline temporal yang benar-benar akan digunakan aplikasi. Ketetapan 350–450 lux dan baseline 20 cm adalah operasionalisasi untuk membuat 40 sequence terkontrol; proposal menetapkan jenis sequence tetapi tidak merinci angka kondisi kendali untuk setiap sequence.

## Protokol penggunaan

1. Instal aplikasi pada POCO.
2. Set alias tetap, misalnya `poco_x5_pro_5g`.
3. Pilih folder Drive.
4. Tekan `Konfigurasi 5.7.2`, isi hasil final kalibrasi statis, centang konfirmasi, lalu Simpan.
5. Pilih sequence dari spinner/checklist.
6. Tekan `Mulai sequence`.
7. Countdown 3 detik dimulai, lalu rekaman 12 detik.
8. Ikuti cue besar pada preview. Setiap perubahan stage memberi haptic feedback.
9. Setelah selesai, data disimpan lokal lalu dicoba sinkron ke Drive.
10. Ulangi sampai 40/40.
11. Lakukan hal yang sama pada Redmi 4X dengan komposisi dan konfigurasi **yang sama**.

Jika sequence salah, ketuk item `SAVED` lalu pilih `Hapus & rekam ulang`. Sequence lain tidak disentuh.

## 28 urutan nominal

Untuk setiap nominal Rp1.000, Rp2.000, Rp5.000, Rp10.000, Rp20.000, Rp50.000, dan Rp100.000 terdapat empat skenario:

- `STABLE`: objek dipertahankan stabil;
- `MOTION`: gerakan ringan kiri-kanan;
- `DISTANCE`: 20 cm → 10 cm → 30 cm → sekitar 20 cm;
- `ORIENTATION`: perubahan orientasi ringan lalu kembali.

Setiap sequence mempunyai bagian ROI kosong di awal dan akhir agar perilaku reset dapat diamati.

## 6 urutan nonuang

Slot yang disediakan:

1. dompet;
2. kartu plastik;
3. nota atau kertas;
4. telapak tangan;
5. kemasan produk;
6. latar kosong.

## 6 urutan pergantian objek

- `TR_01`: Rp1.000 → kosong → Rp2.000;
- `TR_02`: Rp5.000 → kosong → Rp10.000;
- `TR_03`: Rp20.000 → kosong → Rp50.000;
- `TR_04`: Rp100.000 → pergantian langsung → Rp1.000;
- `TR_05`: Rp50.000 → nonuang → Rp20.000;
- `TR_06`: Rp10.000 → pergantian langsung → Rp100.000.

Stage `transition` pada pergantian langsung tidak dipakai sebagai endpoint ground truth karena objek sedang berpindah.

## Audit dataset

Setelah folder perangkat tersedia di komputer:

```bash
python3 tools/audit_sequence_collection.py /path/to/RupiahSequenceCollector/poco_x5_pro_5g --require-complete
python3 tools/audit_sequence_collection.py /path/to/RupiahSequenceCollector/redmi_4x --require-complete
```

Audit memeriksa 40 sequence, komposisi 28/6/6, model SHA-256, hash konfigurasi, file wajib, monotonic timestamp, delapan skor, jumlah skor ~1, dan kecukupan stream.

## Analisis kandidat 5.7.3

Setelah dua perangkat lengkap:

```bash
python3 tools/analyze_sequences.py \
  /path/to/RupiahSequenceCollector/poco_x5_pro_5g \
  /path/to/RupiahSequenceCollector/redmi_4x \
  --out-dir hasil_5_7_3
```

Script memutar ulang semua kombinasi yang direncanakan:

- analysis FPS: 3 dan 5;
- confidence threshold: 0.50 sampai 0.95, langkah 0.05;
- temporal window: 1000, 1500, 2000 ms;
- minimum result: 3;
- smoothing: rata-rata delapan skor kelas.

Output:

- `candidate_metrics.csv`;
- `segment_results.csv`;
- `analysis_summary.json`.

Script **tidak otomatis memilih pemenang akhir**, karena keputusan final harus mengikuti metode skripsi dan didokumentasikan pada 5.7.3.

## Build

Project menyertakan Gradle Wrapper 8.9. Buka dengan Android Studio menggunakan JDK 17, lalu build `app` atau jalankan:

```bash
./gradlew clean :app:assembleDebug :app:testDebugUnitTest
```

APK debug normalnya berada di:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Pemisahan dari collector lama

Application ID project ini adalah:

```text
id.ac.ub.rupiah.sequence
```

Collector citra statis memakai:

```text
id.ac.ub.rupiah.calibration
```

Karena package, storage root, dan Drive root berbeda, menginstal Sequence Collector tidak menghapus atau menimpa 360 citra kalibrasi yang sudah dikumpulkan pada aplikasi lama.
