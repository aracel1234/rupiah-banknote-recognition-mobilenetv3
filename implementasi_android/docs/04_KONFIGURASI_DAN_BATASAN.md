# Konfigurasi, efisiensi, dan batas hasil

## Status setelah kalibrasi kualitas statis 5.7.2

| Parameter | Nilai saat ini | Status |
|---|---:|---|
| `analysis_fps` | 3 | **Belum final**, menunggu kalibrasi lanjutan |
| `threads` | 4 | Mengikuti runtime model terpilih |
| `roi_width_fraction` | **0,90** | **Dikunci 5.7.2** |
| `roi_aspect_ratio` | **1,3420920964096548** | **Dikunci**, berasal dari geometri dataset |
| `roi_height_cap_fraction` | **0,90** | **Dikunci**, konsisten dengan implementasi ROI |
| `blur_variance_min` | **23,74892868863396** | **Dikunci 5.7.2**, hasil Youden dan penyelesaian tie eksplisit |
| `luma_min` | **91,93479241966921** | **Dikunci 5.7.2** |
| `luma_max` | **178,81127789279964** | **Dikunci 5.7.2** |
| `confidence_threshold` | 0,80 | **Belum final**, menunggu 5.7.3 |
| `temporal_window_ms` | 1500 | **Belum final**, menunggu 5.7.3 |
| `minimum_results` | 3 | **Belum final**, menunggu 5.7.3 |
| `clahe_enabled` | **false** | **Dikunci 5.7.2**, tidak ada konfigurasi CLAHE yang memenuhi aturan seleksi |
| `clahe_clip_limit` / `clahe_grid` | `null` / `null` | Tidak digunakan karena CLAHE tidak dipilih |
| `yuv_range` | `limited_bt601` | Konvensi konversi aplikasi |
| `log_enabled` | true | Log diagnostik lokal selama pengembangan |

Konfigurasi operasional berada pada `app/src/main/assets/app_config.json`. Bukti kalibrasi statis berada pada `app/src/main/assets/calibration/`. Aplikasi memverifikasi SHA-256 lock dan kecocokan parameter ROI, blur, luminansi, keputusan CLAHE, dan rentang YUV ketika konfigurasi dimuat.

## Urutan pemeriksaan kualitas

Urutan keputusan tetap mengikuti rancangan dan implementasi yang didokumentasikan hingga Subbab 5.6.2:

1. hitung rata-rata luminansi ROI;
2. terapkan CLAHE hanya jika konfigurasi mengaktifkannya dan ROI berada di bawah ambang redup;
3. periksa batas pencahayaan;
4. periksa Varians Laplacian;
5. lanjutkan ke RGB, resize 224 × 224, dan inferensi apabila ROI lolos.

Karena hasil 5.7.2 menetapkan `clahe_enabled=false`, langkah CLAHE dilewati dan mean Y serta Varians Laplacian menggunakan luminansi Y asli ROI.

## Batas yang masih terbuka

Konfigurasi kualitas statis sudah selesai, tetapi aplikasi belum berada pada status konfigurasi operasional akhir. `analysis_fps`, `confidence_threshold`, `temporal_window_ms`, dan `minimum_results` masih merupakan nilai pengembangan sampai analisis urutan 5.7.3 selesai. Karena itu status aplikasi masih `static_quality_calibrated_postinfer_pending`, bukan `calibrated`.

Setelah 5.7.3 selesai, nilai pascainferensi dan laju analisis harus diperbarui tanpa mengubah parameter statis yang sudah dikunci, kemudian snapshot dan artefak konfigurasi akhir dibuat kembali.
