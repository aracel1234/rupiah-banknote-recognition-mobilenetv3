# Rupiah Calibration Collector

Aplikasi Android terpisah untuk mengumpulkan **citra kalibrasi statis** pada penelitian pengenalan nominal uang Rupiah. Aplikasi sengaja tidak menjalankan model, ROI final, quality gate final, CLAHE, temporal smoothing, atau TTS. Tujuannya adalah menangkap satu frame **CameraX ImageAnalysis** yang sama dengan sumber pipeline produksi, lalu menyimpan data yang dapat dipakai ulang untuk eksperimen parameter.

## Prinsip data

Istilah "mentah" pada aplikasi ini berarti **frame analisis sebelum praproses aplikasi**, bukan RAW sensor (DNG). Kamera Android tetap menggunakan ISP, auto exposure, auto white balance, dan mekanisme kamera perangkat. Hal ini justru sesuai karena eksperimen ingin mengkalibrasi pipeline terhadap citra yang benar-benar diterima aplikasi.

Setiap capture yang diterima menyimpan:
- `frame_rgb.png`: lossless PNG, orientasi sudah dinormalisasi, konversi dari YUV menggunakan limited-range BT.601 yang konsisten dengan pipeline aplikasi;
- `frame_luma.png`: lossless grayscale dari kanal Y;
- `metadata.json`: kondisi eksperimen, perangkat, ukuran aktual, rotationDegrees, hash, path, dan diagnostik;
- update otomatis `manifest.jsonl`, `manifest.csv`, `checklist.json`, dan `checklist.csv`.

Tidak ada citra yang langsung masuk dataset: capture selalu membuka dialog **Verifikasi sebelum simpan**. Tombol Simpan hanya aktif secara logis setelah peneliti mencentang konfirmasi.

## Checklist otomatis

Per perangkat dibuat 360 target:
- 240 citra kualitas = 8 kelas × 3 cahaya × 2 fokus × 5;
- 120 citra ROI = 8 kelas × 3 jarak × 5.

Pengambilan **tidak diwajibkan mengikuti urutan checklist**. Pada panel `Pilih target pengambilan`, peneliti dapat memilih kelompok data (Kualitas/ROI), nominal atau kelas, serta kondisi eksperimen. Aplikasi kemudian memilih ulangan pending terkecil (1–5) pada kombinasi tersebut. Setelah sampel diterima, target berubah menjadi `SAVED` dan, selama pemilihan dilakukan melalui panel, aplikasi otomatis lanjut ke ulangan pending berikutnya pada kombinasi yang sama. Checklist dapat difilter menjadi Belum selesai / Tersimpan / Semua / Kualitas / ROI. Item `PENDING` dapat diketuk untuk memilih target spesifik, sedangkan item `SAVED` dapat diketuk untuk melihat pratinjau dan menghapus citra yang salah agar slot yang sama kembali menjadi `PENDING`.

## Google Drive tanpa credential di APK

Aplikasi menggunakan Android **Storage Access Framework**. Tekan `Pilih folder Drive`, lalu pilih folder Google Drive jika provider Drive tersedia pada perangkat. Izin folder dipertahankan oleh Android dan tidak ada OAuth token, password, atau GitHub token yang ditanam di source code.

Versi 0.2.0 memperbaiki masalah duplikasi folder/file pada provider Google Drive. Versi sebelumnya dapat memanggil `createDirectory()` atau `createFile()` kembali ketika daftar isi Drive belum memperlihatkan objek yang baru dibuat. Google Drive mengizinkan nama yang sama, sehingga dapat muncul folder `poco_x5_pro_5g`/`1000` ganda atau file seperti `manifest(1).csv`. Versi ini menyimpan URI objek Drive yang sudah dibuat, memakai ulang dokumen yang sama, tidak melakukan sinkronisasi index dua kali pada satu capture, dan menolak auto-rename `(1)` daripada membiarkannya masuk ke dataset.

Alur penyimpanan:
1. Simpan ke penyimpanan lokal aplikasi terlebih dahulu.
2. Sinkronkan tiga berkas sampel (`frame_rgb.png`, `frame_luma.png`, `metadata.json`).
3. Setelah status sampel final, `manifest` dan `checklist` disinkronkan **satu kali**.
4. Jika sinkronisasi gagal/offline, data lokal tidak hilang dan status menjadi pending; tekan `Sinkronkan` setelah koneksi tersedia.

Jika folder Drive lama sudah mengandung duplikasi dari versi sebelumnya, aplikasi **tidak menghapus data lama otomatis** karena penghapusan dapat membuang artefak penelitian. Cara paling aman adalah membuat folder Drive baru/kosong untuk versi 0.2.0, pilih folder tersebut, lalu tekan `Sinkronkan`; dataset lokal pada perangkat tetap menjadi sumber utama.

GitHub tidak dijadikan penyimpanan utama karena dataset gambar biner cepat membesar dan menyimpan token GitHub dalam APK tidak aman. Jika Drive provider tidak tersedia, folder lokal tetap dapat disalin manual setelah sesi.

## Menghapus citra yang salah

Versi 0.3.0 menambahkan penghapusan sampel dari checklist.

1. Ubah filter menjadi `Tersimpan` atau `Semua`.
2. Ketuk item `SAVED`.
3. Aplikasi menampilkan pratinjau citra, ID sampel, waktu simpan, dan status sinkronisasi.
4. Tekan `Hapus citra`, lalu konfirmasi.
5. Jika folder Drive aktif, aplikasi terlebih dahulu menghapus folder sampel pada Drive. Penghapusan mengikuti seluruh jalur folder bernama sama yang ditemukan sehingga salinan sampel di struktur duplikat lama juga dapat dibersihkan.
6. Setelah penghapusan cloud berhasil, folder lokal dihapus, semua baris `sample_id` tersebut dikeluarkan dari `manifest.jsonl`, `manifest.csv` dibuat ulang, dan checklist dikembalikan menjadi `PENDING`.
7. `checklist.json`, `checklist.csv`, `manifest.jsonl`, dan `manifest.csv` kemudian disinkronkan ulang.

Jika suatu sampel berstatus `SYNCED`/`PENDING` tetapi folder Drive tidak sedang dipilih, penghapusan diblokir. Pilih kembali folder Drive yang sama terlebih dahulu agar aplikasi tidak meninggalkan salinan cloud yang tidak tercatat.

## Kamera

- CameraX `Preview` + `ImageAnalysis`.
- format analisis eksplisit `YUV_420_888`;
- resolusi referensi 640×480 dengan fallback CameraX `closest lower then higher`;
- `STRATEGY_KEEP_ONLY_LATEST`;
- kamera belakang dikunci untuk collector agar faktor lensa tidak berubah di tengah desain kalibrasi;
- Preview dan ImageAnalysis menggunakan kamera yang sama dan, jika tersedia, ViewPort yang sama.

## Build

Konfigurasi mengikuti lingkungan proyek skripsi:
- Gradle 8.9;
- Android Gradle Plugin 8.7.3;
- Kotlin Android 1.9.25;
- compileSdk 35;
- targetSdk 34;
- minSdk 23;
- Java/Kotlin target 17;
- CameraX 1.4.2.

Folder ini tidak menyertakan binary `gradle-wrapper.jar`. Paling mudah: buka proyek dengan Android Studio dan gunakan Gradle/JDK environment yang sama dengan proyek skripsi, atau salin `gradle/wrapper/gradle-wrapper.jar`, `gradlew`, dan `gradlew.bat` dari proyek `implementasi_android` yang sudah berjalan karena versinya sama-sama Gradle 8.9.

## Penggunaan

1. Instal pada POCO X5 Pro 5G.
2. Set alias tetap, misalnya `poco_x5_pro_5g`.
3. Pilih folder Google Drive tujuan.
4. Pilih `Jenis data` → `Nominal/kelas` → kondisi (cahaya + fokus untuk Kualitas, atau jarak untuk ROI). **Tidak perlu memulai dari Rp1.000** dan tidak ada urutan nominal wajib.
5. Setiap perubahan pilihan langsung mengaktifkan ulangan `PENDING` terkecil pada kombinasi tersebut. Tombol `Terapkan` hanya untuk konfirmasi ulang pilihan. Capture → periksa preview → centang verifikasi → Simpan.
6. Ulangi atau pilih kombinasi lain sesuai kebutuhan; checklist akan terisi otomatis. Bila ada citra salah, pilih filter `Tersimpan`, ketuk sampel tersebut, lalu gunakan `Hapus citra` dan ambil ulang slot yang kembali `PENDING`.
7. Setelah 360/360, lakukan `Sinkronkan` dan audit folder di komputer.
8. Ulangi di Xiaomi Redmi 4X dengan alias `redmi_4x`.

Jarak 10/20/30 cm harus ditentukan secara fisik menggunakan penggaris/penyangga; aplikasi tidak mengestimasi jarak. Kondisi redup/normal/terang dan tajam/blur juga dibentuk secara nyata, bukan melalui edit digital.

## Audit setelah data disalin ke komputer

```bash
python3 tools/audit_collection.py /path/to/RupiahCalibrationCollector/poco_x5_pro_5g
```

Script memeriksa jumlah checklist, jumlah accepted samples, keberadaan file, dan SHA-256 RGB/luma.

## Batas penggunaan

Collector ini hanya untuk **720 citra statis dua perangkat**. Kalibrasi urutan (40 urutan per perangkat / 80 total) tetap harus dikumpulkan melalui pipeline pengenalan utama atau mode logging yang menyimpan skor inferensi frame-per-frame, karena parameter pascainferensi tidak dapat ditentukan hanya dari foto statis.
