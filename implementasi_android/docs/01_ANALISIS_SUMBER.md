# Analisis sumber dan keputusan integrasi

## 1. Bahan yang benar-benar digunakan

- `pengembangan_model.zip`: hasil pengembangan, termasuk checkpoint, ringkasan tahap 1–7, kandidat TFLite, metadata, hasil seleksi, dan `07_compare/final_assets`.
- `pengembangan_model (Delete Android Benchmark except main folder).zip`: sumber pipeline data, konstruksi model, pelatihan, fine-tuning, pengulangan seed, konversi, seleksi, pemeriksaan seleksi, dan sumber benchmark Android.
- Skripsi **Bab 1–Bab 5.4**, terutama 3.8.1–3.8.4, 4.2–4.7, 5.2–5.4, serta kerangka 5.5–5.11.
- Gambar rancangan antarmuka yang dilampirkan.
- Skrip persiapan data untuk memastikan lokasi `04_dedup/money_unique_manifest.csv` dan kolom `file_path` yang digunakan alat geometri ROI.

Ini analisis integrasi berdasarkan kode dan artefak tersimpan, bukan pengulangan seluruh eksperimen. Laporan dan sumber tahap sebelumnya tidak diedit. Dataset asli dan sampel kalibrasi aplikasi baru tidak tersedia di paket ini.

## 2. Rantai model

| Tahap | Temuan artefak | Implikasi pada Android |
|---|---|---|
| 1, pipeline | RGB float32, resize bilinear 224×224, antialias false, augmentasi hanya data latih | Kamera tidak memakai augmentasi saat inferensi |
| 2, arsitektur | MobileNetV3-Small dengan preprocessing internal, GAP, dropout 0,20, Dense 8 softmax | Jangan membagi piksel dengan 255 atau menambahkan softmax |
| 3, head | Terpilih batch 32, LR awal 0,001, epoch 7, Macro F1 validasi 0,815203 | Tidak membawa optimizer/checkpoint training ke APK |
| 4, fine-tuning | Proporsi atas 35%, LR awal 0,00003, epoch 20, Macro F1 0,936012 | Bobot model yang sudah selesai menjadi sumber berikutnya |
| 5, repeat | Seed 42, 123, 2026; seed 42 dipilih | Android tidak mengulangi pencarian seed |
| 6, TFLite | Empat kandidat tersedia; 400 sampel representatif; metadata menyatakan validasi Android selesai | Gunakan artefak TFLite yang sudah diseleksi |
| 7, selection | `selected_candidate = dynamic_range`, keputusan tersimpan sebelum pembukaan test | Model final langsung menjadi aset aplikasi |

Nilai LR dalam catatan akhir tahap 5 sekitar 0,000006 merupakan nilai setelah scheduler; jangan menyamakannya dengan LR awal konfigurasi fine-tuning. Artefak sebelumnya juga sudah memuat evaluasi 4.376 citra uji. Pembuatan proyek ini tidak menjalankan evaluasi tersebut lagi.

## 3. Model final yang disertakan

| Properti | Nilai |
|---|---|
| Kandidat | `dynamic_range` |
| Ukuran asli | 1.107.648 byte / 1,056335 MiB |
| SHA-256 | `fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676` |
| Input | `[1,224,224,3]`, NHWC, RGB, float32 `[0,255]` |
| Output | `[1,8]`, float32, probabilitas softmax |
| Urutan kelas | `1000, 2000, 5000, 10000, 20000, 50000, 100000, nonuang` |
| Preprocessing internal | `x / 127.5 - 1`, sudah menjadi bagian graf |
| Runtime acuan seleksi | TFLite 2.17.0, CPU XNNPACK, 4 thread, tanpa GPU/NNAPI |

`tensor_contract.json` final menyimpan tipe/bentuk/kuantisasi/operator tetapi tidak mengulang seluruh semantik resize dan rentang eksternal. Semantik tersebut ditelusuri dari `02_build_model.py`, `01_data_pipeline.py`, dan fungsi `image()` pada `06_build_tflite.py`. Aset final disalin tanpa mengubah kontrak asli.

## 4. Mengapa tidak menggunakan Full INT8

Hasil **validasi tersimpan**, bukan pengukuran baru:

| Kandidat | Accuracy | Macro F1 | Ukuran MiB |
|---|---:|---:|---:|
| FP32 | 0,938785 | 0,936012 | 3,570663 |
| FP16 | 0,937643 | 0,934808 | 1,817219 |
| Dynamic Range | 0,950662 | 0,948583 | 1,056335 |
| Full INT8 | 0,482869 | 0,477734 | 1,159187 |

Batas kualitas 1-SE pada keputusan adalah 0,945082. Hanya Dynamic Range yang lolos; himpunan Pareto selanjutnya berisi satu kandidat. Jadi jangan menulis bahwa keputusan ini membuktikan keunggulan kecepatan statistik Dynamic Range atas seluruh kandidat layak: pada tahap itu hanya satu kandidat tersisa. Ukuran kecil atau nama INT8 saja tidak cukup untuk memilih model aplikasi.

Paket aplikasi hanya membawa model final, label, kontrak, identitas, dan selection lock. Tidak membawa tiga kandidat lain, input benchmark `.f32`, hasil training `.keras`, dataset, atau CSV prediksi ke dalam APK.

## 5. Batas interpretasi hasil benchmark

Pada lock, perangkat benchmark adalah POCO X5 Pro 5G, Android 14. Median inferensi sekitar 33,05 ms, tetapi P95 sekitar 519,66 ms. Ini menunjukkan sebaran waktu cukup lebar. Nilai tersebut tidak mencakup keseluruhan kamera–ROI–kualitas–konversi–stabilisasi–audio aplikasi.

Batas awal 3 FPS dalam proyek bukan laju akhir yang sudah dibuktikan. Bahkan P95 model tersimpan saja belum mendukung klaim 3 FPS yang konsisten. Runtime membuang bingkai dan tidak memaksakan target ketika pemrosesan lambat. Keputusan laju akhir harus mengikuti P95 pipeline pada kedua perangkat dalam metode skripsi; jika tidak ada kandidat 3/5 FPS yang layak, hasil itu harus dilaporkan, bukan dibuat seolah telah memenuhi batas.

## 6. Hal yang harus tetap terbuka

- Naskah terbaru menetapkan POCO X5 Pro 5G dan Xiaomi Redmi 4X, bukan mengandalkan rencana perangkat lama dari percakapan sebelumnya.
- Median rasio aspek uang hasil kurasi tidak dapat dihitung dari ZIP sumber kode saja. Nilai 2,2 yang disertakan bersifat sementara; alat penghitungan median disediakan.
- Data kalibrasi kamera untuk blur, cahaya, ROI, CLAHE, threshold, dan waktu belum ada. Tidak ada nilai final yang dikarang.
- Citra latihan berupa hasil crop anotasi; ROI kamera adalah crop tetap. ROI tidak mendeteksi batas uang secara otomatis. Posisi uang dan proporsi latar tetap penting.
- Kelas nonuang merupakan mekanisme penolakan terlatih, bukan jaminan bahwa semua objek asing atau beberapa uang sekaligus selalu ditolak.
- Aplikasi mengklasifikasikan nominal, tidak memeriksa keaslian uang dan tidak menghitung banyak lembar.
