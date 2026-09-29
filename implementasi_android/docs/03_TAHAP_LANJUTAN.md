# Urutan lanjutan setelah kalibrasi kualitas statis

Model Dynamic Range, geometri ROI, ambang blur, ambang pencahayaan, dan keputusan penggunaan CLAHE telah diperoleh melalui tahapan sampai 5.7.2. Proyek Android saat ini telah diselaraskan dengan hasil tersebut.

## Status saat ini

Konfigurasi statis yang sudah dikunci adalah ROI 0,90, rasio aspek 1,3420920964096548, height cap 0,90, ambang blur 23,74892868863396, ambang luminansi 91,93479241966921 dan 178,81127789279964, serta CLAHE nonaktif.

Parameter yang belum final adalah `analysis_fps`, `confidence_threshold`, `temporal_window_ms`, dan `minimum_results`. Nilai yang masih berada di `app_config.json` untuk parameter tersebut hanya mempertahankan perilaku pengembangan sampai 5.7.3 selesai.

## Langkah berikutnya

1. Selesaikan pengumpulan dan pemeriksaan 40 urutan per perangkat untuk 5.7.3.
2. Analisis ambang keyakinan dan penghalusan temporal sesuai Subbab 3.8.4 menggunakan data urutan, bukan data uji akhir.
3. Tentukan laju analisis yang dapat digunakan bersama pada kedua perangkat sesuai metode penelitian.
4. Perbarui hanya parameter yang masih berstatus pending di `app_config.json`.
5. Ubah status menjadi `calibrated` hanya setelah seluruh konfigurasi operasional benar-benar dikunci.
6. Jalankan ulang build, pemeriksaan perangkat, dan `tools/10_snapshot.py` untuk membuat snapshot implementasi akhir.

Jangan mengubah kembali parameter ROI, blur, luminansi, atau keputusan CLAHE berdasarkan data urutan 5.7.3, karena parameter tersebut sudah dikunci menggunakan bukti kalibrasi 5.7.2.
