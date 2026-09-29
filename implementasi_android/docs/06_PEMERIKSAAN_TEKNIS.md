# Catatan pemeriksaan teknis paket setelah kalibrasi 5.7.2

## Pemeriksaan yang dilakukan pada revisi ini

- Mencocokkan hasil Stage 8 terhadap hash Stage 4, Stage 5, Stage 6, dan Stage 7.
- Memastikan `static_quality_config_lock.json` mengunci ROI 0,90, rasio aspek 1,3420920964096548, height cap 0,90, ambang blur 23,74892868863396, ambang luminansi 91,93479241966921 dan 178,81127789279964, serta CLAHE nonaktif.
- Menyalin bukti kalibrasi statis ke `app/src/main/assets/calibration/` tanpa mengubah aset model.
- Menambahkan pemeriksaan hash dan kecocokan nilai kalibrasi pada `AppConfig.load()`.
- Mengubah `RoiGeometry` agar height cap berasal dari konfigurasi yang dikunci dan tidak lagi berupa konstanta tersembunyi.
- Mempertahankan urutan keputusan kualitas sesuai laporan terbaru: CLAHE bersyarat bila diaktifkan, gerbang pencahayaan, lalu gerbang ketajaman.
- Mempertahankan ModelRunner, TemporalDecision, CameraController, SpeechOutput, MainActivity, dan artefak model agar perilaku 5.6 di luar parameter kualitas tidak berubah selama 5.7.3 masih berlangsung.

## Yang masih harus dilakukan pada perangkat pengguna

- Build ulang `:app:assembleDebug` setelah revisi konfigurasi.
- Jalankan aplikasi pada POCO X5 Pro 5G dan Redmi 4X untuk memastikan konfigurasi statis termuat tanpa kegagalan verifikasi bukti.
- Pastikan ROI overlay berubah mengikuti fraksi 0,90 dan log sesi memuat status konfigurasi serta hash lock statis.
- Selesaikan pengumpulan dan analisis data urutan 5.7.3 sebelum mengubah ambang keyakinan, jendela temporal, minimum hasil, atau laju analisis menjadi nilai final.

Revisi ini tidak mengklaim 5.7.3, 5.7.4, atau pengujian Bab 6 telah selesai.
