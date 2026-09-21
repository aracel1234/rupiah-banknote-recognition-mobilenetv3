# Urutan lanjutan setelah tahap 7

Nomor 08–10 pada alat bantu adalah kelanjutan organisasi proyek, bukan perubahan penomoran bab/metode. Kode Android berjalan sebagai aplikasi; Python hanya dipakai untuk pekerjaan aset di laptop.

## Langkah 1 — Pisahkan proyek aplikasi dari benchmark

Simpan proyek baru di folder Android tersendiri. Jangan memakai Activity benchmark sebagai halaman utama produk. Source/output pengembangan model tetap di lokasi semula. Model terpilih sudah ada dalam ZIP sehingga langkah salin manual tidak wajib.

Jika ingin mengimpor ulang dari hasil tahap 7 di laptop:

```bash
python3 tools/08_import_model.py --stage7 "$HOME/Downloads/Skripsi/pengembangan_model/07_compare"
```

Alat memeriksa status tahap 7, SHA-256 selection lock/model/label, kelas, dan kontrak sebelum menyalin aset. Artefak lain ditolak karena proyek ini dibuat untuk pemenang spesifik yang dianalisis. Tidak ada proses memilih ulang model.

## Langkah 2 — Siapkan lingkungan dan bangun aplikasi

Ikuti README untuk setup wrapper, SDK, sinkronisasi Android Studio, dan Run. Versi dependency dikunci. `targetSdk=34` adalah keputusan kompatibilitas proyek pemasangan langsung pada perangkat penelitian; bukan klaim memenuhi persyaratan publikasi Play Store terbaru.

## Langkah 3 — Pahami implementasi per inkremen

| Inkremen Mobile-D | Kode yang dibaca | Hasil implementasi |
|---|---|---|
| I | `MainActivity`, `CameraController`, `RoiGeometry`, `YuvRoi`, `RoiOverlay` | Izin, kamera belakang/depan, preview, orientasi, ROI |
| II | `FramePreprocessor`, `ModelRunner` | RGB float32, bilinear, integritas model, inferensi delapan kelas |
| III | `QualityGate`, `LuminanceClahe`, `AppConfig` | Pemeriksaan kualitas dan opsi CLAHE |
| IV | `TemporalDecision`, `SpeechOutput`, `RecognitionSession` | Stabilisasi, pengendalian nominal, keluaran suara |

Paket berisi integrasi seluruh inkremen, tidak memerlukan copy-paste satu berkas besar. Pemisahan inkremen membantu membaca dan mendokumentasikan pengembangan; paket tidak menyatakan bahwa seluruh kriteria pemeriksaan perangkat Mobile-D telah lulus.

## Langkah 4 — Lengkapi geometri ROI dari data yang sudah dikurasi

Langkah ini menghitung statistik dataset yang ada, bukan menjalankan uji aplikasi. PNG asli berada di laptop pengguna, bukan dalam ZIP ini.

```bash
python3 tools/09_roi_aspect.py \
  --root "$HOME/Downloads/Skripsi/persiapan_data" \
  --out docs/roi_geometry.json
```

Gunakan nilai `roi_aspect_ratio` dari laporan itu untuk mengganti 2,2 pada `app_config.json`. Alat menggunakan w/h aktual PNG uang unik, tidak menukar sisi secara otomatis. Jika hasil berada di luar batas 1–4 yang didukung konfigurasi awal aplikasi, periksa orientasi/kurasi sumber dan sesuaikan rancangan secara eksplisit; jangan membulatkan diam-diam. Pemilihan proporsi lebar 0,70/0,80/0,90 masih menunggu kalibrasi kamera.

## Langkah 5 — Penentuan parameter aplikasi, belum dilakukan dalam pekerjaan ini

Skrip lama tahap 6 mengkalibrasi **kuantisasi model**, sedangkan subbab 3.8.3–3.8.4 mengatur **parameter aplikasi**. Keduanya berbeda. Jangan menganggap representative dataset INT8 telah menentukan threshold blur atau TTS.

Naskah mengharuskan data kalibrasi terpisah pada tiap perangkat: 240 citra kualitas, 120 citra ROI, dan 40 urutan. Jumlah total dua perangkat menjadi 480 citra kualitas, 240 citra ROI, dan 80 urutan. Data tersebut belum dilampirkan. Karena pengguna meminta belum masuk pengujian, pengumpulan/perhitungan ini tidak dijalankan, tidak dibuat hasil palsunya, dan status konfigurasi tetap pengembangan.

Tahap berikutnya saat siap: tentukan ROI dan kualitas, putuskan penggunaan CLAHE, tentukan laju yang layak pada kedua perangkat, lalu threshold dan W. Satu konfigurasi bersama harus mengikuti hasil metode skripsi. Jangan menyetel berdasarkan data test klasifikasi yang sudah dibuka pada tahap 7. Log ringkas yang ada belum menggantikan pencatatan seluruh urutan kalibrasi.

## Langkah 6 — Catat versi implementasi

Sesudah sumber/config diperbarui secara sah:

```bash
python3 tools/10_snapshot.py --out docs/implementation_snapshot.json
```

Ini membuat daftar hash sumber dan aset serta status konfigurasi. Snapshot pengembangan bukan penguncian parameter ilmiah. Sesudah tersedia keputusan kalibrasi sungguhan, catat bukti keputusan dan SHA-256-nya dalam `calibration_evidence_sha256`, baru gunakan status `calibrated`. Perubahan flag saja tidak membuktikan proses kalibrasi sudah dilakukan.

## Batas pekerjaan saat ini

Luaran mencakup Initialize dan implementasi Productionize serta mekanisme sumber daya untuk Stabilize. Kalibrasi akhir dan verifikasi perangkat Stabilize belum selesai. Fase **System Test and Fix / Bab 6** belum dijalankan. Tidak ada modul benchmark, penghitungan accuracy baru, pengukuran baterai, atau pengujian pengguna yang dimasukkan ke aplikasi ini.
