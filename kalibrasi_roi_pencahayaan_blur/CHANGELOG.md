# Changelog

## 0.3.0-calibration

- Menambahkan filter `Tersimpan` untuk memudahkan audit hasil capture.
- Item `SAVED` sekarang dapat diketuk untuk menampilkan pratinjau, ID sampel, waktu simpan, dan status sinkronisasi.
- Menambahkan `Hapus citra` dengan konfirmasi kedua agar sampel yang salah dapat diambil ulang.
- Penghapusan memperbarui folder lokal, `manifest.jsonl`, `manifest.csv`, `checklist.json`, dan `checklist.csv`.
- Slot checklist yang dihapus dikembalikan ke `PENDING` dengan `sync_status=NOT_SAVED`.
- Jika Google Drive aktif, folder sampel dihapus dari Drive lebih dulu sebelum data lokal diubah.
- Traversal penghapusan mengikuti semua folder bernama sama pada struktur lama sehingga sampel yang tersimpan pada cabang duplikat lama dapat dibersihkan.
- Sampel yang pernah disinkronkan tidak dapat dihapus saat folder Drive tidak aktif; ini mencegah citra cloud tertinggal tanpa manifest.
- Setelah penghapusan, index/manifest Drive disinkronkan ulang.

## 0.2.0-calibration

- Pengambilan tidak lagi bergantung pada urutan checklist.
- Menambahkan placeholder `Pilih jenis data…` dan `Pilih nominal/kelas…` agar Rp1.000 tidak menjadi target default.
- Perubahan pilihan jenis data, nominal/kelas, pencahayaan/fokus/jarak langsung memilih ulangan `PENDING` terkecil pada kombinasi tersebut.
- Item checklist tetap dapat diketuk untuk memilih target spesifik.
- Memperbaiki sinkronisasi Google Drive agar tidak menyinkronkan `manifest/checklist` dua kali dalam satu capture.
- Menambahkan cache URI dokumen/folder Drive yang baru dibuat untuk menghindari `createDirectory/createFile` berulang ketika listing Google Drive tertunda.
- Menolak auto-rename provider seperti `manifest(1).csv` daripada membiarkan duplikat masuk ke struktur penelitian.
- Mencegah folder bertingkat ganda bila folder yang dipilih pengguna sudah bernama `RupiahCalibrationCollector` atau sudah merupakan folder perangkat.
- Data lama di Drive tidak dihapus otomatis. Untuk migrasi paling aman, gunakan folder Drive baru/kosong dan lakukan sinkronisasi ulang dari penyimpanan lokal aplikasi.
