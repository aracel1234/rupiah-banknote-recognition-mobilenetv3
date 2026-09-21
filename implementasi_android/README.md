# Pengenalan Nominal Rupiah — proyek Android

Proyek lanjutan setelah tahap 7, versi `0.1.0-dev`. Model Dynamic Range hasil seleksi sudah disertakan. Tidak perlu mengulang pelatihan, konversi, atau benchmark model. Aplikasi menggunakan Kotlin, XML Views, CameraX, TensorFlow Lite lokal, dan suara Bahasa Indonesia luring.

**Status:** implementasi sumber aplikasi dan pemeriksaan statis. Belum dikompilasi menjadi APK di lingkungan penyusunan ini karena Android SDK, Gradle, dan compiler Kotlin tidak tersedia; akses unduhan build tools juga tidak berhasil. Tidak ada hasil pengujian perangkat atau klaim hemat daya yang dibuat. Parameter aplikasi masih `development_uncalibrated`.

## Mulai di KDE Neon

1. Ekstrak ZIP ke folder baru, misalnya `~/Downloads/Skripsi/android-rupiah/RupiahRecognition`. Jangan timpa proyek benchmark lama.
2. Siapkan Android Studio, JDK 17, Android SDK Platform 35, Build Tools 34.0.0, dan Platform Tools. Pasang komponen SDK melalui SDK Manager. JDK 17 dipilih sebagai Gradle JDK.
3. Dari terminal di folder proyek, jalankan:

   ```bash
   bash tools/00_setup_gradle.sh
   ```

   Langkah satu kali ini mengunduh distribusi resmi Gradle 8.9, memeriksa SHA-256 terhadap checksum resmi, dan membuat wrapper resmi. Internet diperlukan untuk pemasangan dependensi di laptop. Jika JDK 17 belum ada, pasang melalui pengelola paket KDE Neon. Jika unduhan gagal, perbaiki koneksi/proxy lalu jalankan ulang; tidak ada model yang diubah.
4. Di Android Studio pilih **Open**, pilih folder yang memuat `settings.gradle.kts`, lalu **Sync Project with Gradle Files**. Tidak perlu membuat Empty Activity lagi dan jangan menerima perubahan versi dependensi secara otomatis.
5. Aktifkan USB debugging pada HP, sambungkan kabel data, dan setujui dialog otorisasi perangkat. Pilih HP sebagai perangkat tujuan.
6. Siapkan mesin TTS dengan suara Bahasa Indonesia yang sudah diunduh dan dapat digunakan tanpa jaringan. Pengunduhan suara dilakukan lewat setelan Android; aplikasi sendiri tidak mengakses internet.
7. Tekan **Run app**. Izinkan kamera. Kamera belakang menjadi kamera awal. Ini adalah menjalankan hasil implementasi; paket tidak menjalankan protokol pengujian penelitian.

Alternatif setelah SDK dan wrapper siap:

```bash
./gradlew :app:assembleDebug
```

APK berada di `app/build/outputs/apk/debug/`. Pilih APK ABI yang cocok atau `app-universal-debug.apk`. Perintah pemasangan contoh untuk satu perangkat:

```bash
adb devices
adb install -r app/build/outputs/apk/debug/app-universal-debug.apk
```

Jika beberapa perangkat terhubung, tambahkan `adb -s SERIAL`. Paket menyediakan ARM 32-bit dan ARM 64-bit; emulator x86 tidak menjadi sasaran. Minimum Android 6/API 23. Dukungan versi OS tidak membuktikan performa pada semua HP lama.

## Isi yang perlu dibaca

| Berkas | Isi |
|---|---|
| `docs/01_ANALISIS_SUMBER.md` | Bukti dari skrip, hasil seleksi, dan skripsi terbaru |
| `docs/02_ARSITEKTUR_DAN_ALUR.md` | Tanggung jawab setiap kelas dan aturan pipeline |
| `docs/03_TAHAP_LANJUTAN.md` | Urutan kerja setelah tahap 7, sebelum pengujian sistem |
| `docs/04_KONFIGURASI_DAN_BATASAN.md` | Parameter sementara, kalibrasi yang belum dilakukan, batas build |
| `docs/05_KETERLACAKAN.md` | Pemetaan kebutuhan dan Bab 5.5–5.11 ke kode |
| `docs/06_PEMERIKSAAN_TEKNIS.md` | Pemeriksaan yang dilakukan dan yang belum dapat dilakukan |
| `app/src/main/assets/app_config.json` | Seluruh parameter operasional dalam satu berkas |
| `tools/08_import_model.py` | Impor ulang aset terpilih secara terverifikasi jika diperlukan |
| `tools/09_roi_aspect.py` | Hitung median rasio aspek dari PNG uang hasil kurasi |
| `tools/10_snapshot.py` | Catat identitas versi sumber dan konfigurasi |

## Cara aplikasi digunakan

Arahkan satu lembar uang ke dalam panduan ROI. Aplikasi menahan citra buram, pencahayaan yang ditolak, prediksi nonuang, dan prediksi yang belum meyakinkan/stabil. Nominal diterima tampil di bawah pratinjau dan diucapkan satu kali. Keluarkan uang selama setidaknya satu jendela penolakan agar nominal yang sama dapat diucapkan kembali. Pergantian kamera mengosongkan riwayat. Tombol kanan menghentikan sesi dan berubah menjadi **Mulai Pengenalan**. Saat aplikasi masuk latar belakang, kamera, model, dan TTS dilepas; kembali ke aplikasi memulai sesi baru jika sebelumnya belum dihentikan pengguna.

Ukuran ROI, ambang, dan laju yang disertakan hanya nilai awal pengembangan. Jika penolakan terlalu sering, jangan menyimpulkan model rusak atau mengganti nilai berdasarkan data uji. Lanjutkan penentuan parameter sesuai skripsi pada tahap berikutnya.

Untuk menghasilkan APK rilis setelah implementasi selesai, gunakan **Build → Generate Signed App Bundle / APK → APK**, simpan keystore sendiri, dan pilih varian release. Konfigurasi release mengaktifkan R8 dan resource shrinking. Jangan membagikan keystore atau memasukkannya ke repositori. Tidak ada sertifikat penandatanganan pribadi yang disertakan.
