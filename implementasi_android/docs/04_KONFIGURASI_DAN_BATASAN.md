# Konfigurasi, efisiensi, dan batas hasil

## Nilai awal yang disertakan

| Parameter | Awal | Status / alasan |
|---|---:|---|
| `analysis_fps` | 3 | Batas atas sementara; bukan hasil pemilihan laju berdasarkan P95 |
| `threads` | 4 | Mengikuti runtime acuan seleksi; bukan kesimpulan paling hemat daya |
| `roi_width_fraction` | 0,80 | Salah satu kandidat metode, belum dipilih lewat kalibrasi |
| `roi_aspect_ratio` | 2,20 | Perkiraan sementara; ganti dengan median data kurasi |
| `blur_variance_min` | 35 | Nilai awal rekayasa; bukan ambang Youden hasil penelitian |
| `luma_min` / `luma_max` | 45 / 220 | Nilai awal rekayasa, bukan batas pencahayaan terkalibrasi |
| `confidence_threshold` | 0,80 | Kandidat awal; skor softmax bukan probabilitas benar terkalibrasi |
| `temporal_window_ms` | 1500 | Kandidat metode, belum hasil pemilihan bersama dua perangkat |
| `minimum_results` | 3 | Mengikuti persyaratan minimal bukti temporal |
| `clahe_enabled` | false | Baseline; manfaat CLAHE belum dibuktikan |
| `clahe_clip_limit` / `clahe_grid` | 2 / 4 | Baru digunakan jika CLAHE dipilih nanti |
| `yuv_range` | limited_bt601 | Konvensi konversi eksplisit; kesetaraan kamera perlu pemeriksaan perangkat |
| `log_enabled` | true | Log diagnostik terbatas selama pengembangan |

Semua nilai ini berada pada `app/src/main/assets/app_config.json`. Perubahan membutuhkan build/pemasangan ulang. Tidak ada menu teknis yang membebani pengguna tunanetra. Konfigurasi untuk model tetap float32 karena model yang benar-benar terpilih mempunyai antarmuka itu; tidak ada cabang INT8 yang tidak diperlukan pada produk ini.

## Cara mengurangi beban yang sudah diterapkan

- Satu model 1,06 MiB; hanya satu runtime lokal, tanpa TensorFlow penuh, OpenCV native, jaringan, akun, database, atau framework UI tambahan.
- XML Views dan satu layar utama.
- Permintaan resolusi kamera 640×480, bukan resolusi foto maksimum. CameraX tetap boleh memilih fallback.
- Throttle sebelum membaca piksel; pemeriksaan Y sebelum RGB/inferensi.
- Buffer luminansi, RGB ROI, input dan output dipakai ulang selama dimensi tetap.
- Satu worker; `KEEP_ONLY_LATEST`; ImageProxy selalu dilepas.
- Model dimuat per sesi, tidak per frame. Pergantian kamera mempertahankan model dan TTS.
- R8/resource shrinking untuk release; APK ARM per ABI menghindari native library ABI lain pada APK perangkat tertentu.
- Tidak ada penyimpanan frame; log diputar dan dibatasi.
- Tidak ada pekerjaan kamera/inferensi saat aplikasi berhenti atau masuk latar belakang.

Pilihan ini mengurangi pekerjaan yang tidak diperlukan, tetapi tidak memberi angka penghematan baterai tanpa pengukuran. Layar dan kamera tetap menggunakan energi; `FLAG_KEEP_SCREEN_ON` hanya aktif saat sesi berjalan agar layar tidak terkunci di tengah penggunaan. Tidak ada wake lock layanan background.

Empat thread dipertahankan agar runtime awal sesuai catatan seleksi. Bila kelak thread dikurangi demi daya, catat sebagai konfigurasi baru dan jangan menggunakan angka benchmark empat thread untuk mengklaim performa konfigurasi tersebut.

## Batas teknis yang masih terbuka

1. APK belum dibangun atau dipasang di sini. Kompatibilitas kompilasi dan native runtime tetap perlu dibuktikan lewat build Android Studio pada lingkungan pengguna.
2. Belum ada pemeriksaan kesetaraan 16 citra referensi yang direncanakan subbab 3.8.2. Tidak ada klaim tensor kamera identik dengan citra dataset.
3. Belum ada hasil kalibrasi kualitas atau temporal dari perangkat. Konfigurasi bawaan dapat terlalu longgar atau ketat.
4. Implementasi CLAHE tidak mengklaim persamaan numerik dengan OpenCV; kalibrasi harus memakai implementasi yang sama.
5. Ukuran model bukan ukuran APK, dan ukuran APK bukan RAM proses. APK akhir, RSS/PSS, latensi aplikasi, dan daya belum diukur.
6. PreviewView bersama ViewPort dan ROI terpusat dirancang untuk menyelaraskan area; perilaku perangkat dan font/orientasi ekstrem belum diinspeksi pada Android.
7. Suara luring bergantung pada engine dan voice yang dipasang pada perangkat. Aplikasi menolak memulai pengenalan jika suara luring Bahasa Indonesia tidak tersedia.
8. ZIP menyediakan sumber untuk pemasangan langsung pada HP ARM Android 6 ke atas. Persyaratan distribusi Play Store dan perangkat 16 KiB page-size bukan cakupan build ini.
9. Log ringkas bukan dataset penelitian. Peristiwa request TTS berarti permintaan diterima engine; `tts_start` dan `tts_done` dicatat terpisah. Ini tidak sama dengan pengukuran onset audio fisik.
