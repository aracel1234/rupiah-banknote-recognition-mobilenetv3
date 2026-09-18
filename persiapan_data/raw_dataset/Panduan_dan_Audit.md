# Panduan kode dan penempatan revisi

## Keputusan struktur

Susunan 5.1.1 Akuisisi dan Identifikasi Sumber Dataset serta 5.1.2 Implementasi Penggabungan Dataset Uang sesuai dengan urutan pekerjaan. Akuisisi menjelaskan masukan yang benar-benar digunakan, sedangkan penggabungan menjelaskan transformasinya. Pada PDF skripsi yang tersedia, Subbab 3.4.1 Akuisisi, Asal, dan Lisensi Dataset sudah ada pada halaman tercetak 96–98 (mulai halaman PDF 109). Bab III memuat metode dan kriteria; rincian sumber beserta hasil aktual dapat ditempatkan di Bab V. Jangan menyatakan bahwa Bab III sama sekali belum membahas asal dataset.

## Temuan yang sudah diverifikasi

- Jumlah sepuluh sumber uang dalam CSV tepat 40.344, sama dengan jumlah entri images dalam JSON referensi.
- JSON memuat 40.062 anotasi, tujuh kategori, 37.629 gambar dengan satu anotasi, 930 gambar dengan banyak anotasi, dan 1.785 gambar tanpa anotasi. Sebanyak 38.559 gambar memiliki anotasi. ID gambar dan anotasi masing-masing unik.
- Hasil audit historis juga mencatat 40.344 berkas gambar pada disk. Pemeriksaan saat ini menghitung metadata; berkas gambar lengkap tidak tersedia untuk diperiksa ulang.
- Kategori tidak terpetakan menyebabkan anotasi dibuang, bukan otomatis menghapus berkas gambar. Menghapus 1.785 gambar tanpa anotasi sekarang akan mengubah dataset historis. Tidak dilakukan dalam kode baru.
- Nama null dan 0 tidak ada dalam pemetaan. Angka category_id 0 tidak otomatis dibuang: yang menentukan adalah nama kelas. Contoh ZIP justru mempunyai kategori ID 0 berupa nama kelompok, bukan nama literal 0. Contoh ZIP bukan sumber penelitian.
- Daftar CSV juga memuat 75ribu dan 75000; keduanya tidak masuk pemetaan. Gambar yang memuat kategori itu tidak otomatis dihapus jika berkasnya ditemukan.
- Kode lama salah memakai ann_id_counter. Penghitung yang didefinisikan adalah ann_id_gen. Kode baru menggunakan len(annotations) + 1 untuk menghasilkan ID berurutan yang sama dengan penghitung yang benar.
- JSON memakai ds1, ds10, ds2, ..., ds9, bukan ds01, ds02, ..., ds10. Mengganti awalan dan urutan mengubah identitas dan urutan ID. Kode baru membaca folder ds01–ds10 tetapi sengaja menghasilkan awalan dan urutan historis.
- JSON tidak memuat entri gambar ds9_test. Ini tidak membuktikan folder test tidak pernah ada; mungkin kosong atau tidak menjadi bagian keluaran. Kode tetap memeriksa train/valid/test dan mencatat JSON yang tidak tersedia.
- CSV mencatat 8.002 kandidat nonuang; laporan audit lama mencatat 8.000. Penyebab selisih dua belum diketahui. Jangan mengklaim dua gambar terhapus sebagai duplikat tanpa bukti.
- ds09 dan ds10 tertulis tujuh kelas dalam CSV tetapi daftar namanya memuat delapan label. ds09 mencantumkan 75000; ds10 mencantumkan null. Daftar asli tidak diubah; perbedaan dicatat pada lampiran.
- Lisensi pada dokumen adalah catatan CSV historis. Tidak dilakukan verifikasi menyeluruh atas seluruh halaman repositori dan hak setiap citra pada pekerjaan ini.

## Cara menjalankan satu skrip

Python 3 dan pustaka standar sudah cukup; tidak perlu TensorFlow, pandas, atau paket tambahan.

1. Letakkan 00_prepare_merge_dataset.py di /home/aracel/Downloads/Skripsi/.
2. Siapkan raw_data/ds01 sampai raw_data/ds10 sesuai urutan CSV. Jangan menukar nomor sumber. Pertahankan versi, nama gambar, urutan entri JSON, dan berkas anotasi sumber. Pilih versi ekspor yang sama, bukan otomatis versi terbaru.
3. Jalankan pemeriksaan kelas terlebih dahulu:

```bash
cd /home/aracel/Downloads/Skripsi
python 00_prepare_merge_dataset.py
```

Mode ini menampilkan nama kategori per sumber serta kategori tujuan, termasuk yang tidak dipetakan. Belum ada gambar disalin atau folder keluaran dibuat. Tinjau GROUPS di bagian awal skrip jika ada variasi nama yang belum tercakup. Untuk mereproduksi arsip lama, jangan menambahkan kategori di luar tujuh nominal atau mengubah alias tanpa memeriksa akibatnya terhadap referensi.

4. Letakkan salinan JSON historis all_data_merged(1).json di /home/aracel/Downloads/Skripsi/. Jangan menaruhnya sebagai berkas keluaran yang akan ditimpa.
5. Jalankan penggabungan dan pembandingan:

```bash
python 00_prepare_merge_dataset.py --merge --reference '/home/aracel/Downloads/Skripsi/all_data_merged(1).json'
```

Keluaran default:

- /home/aracel/Downloads/Skripsi/merge_dataset/all_images/
- /home/aracel/Downloads/Skripsi/merge_dataset/all_data_merged.json
- /home/aracel/Downloads/Skripsi/merge_dataset/merge_report.json

Nama all_data_merged(1).json dipakai sebagai referensi karena itu nama lampiran; keluaran memakai all_data_merged.json agar cocok dengan nama yang dibaca skrip 01/02. JSON baru tidak menambah field laporan di dalam images/annotations/categories.

Apabila folder merge_dataset sudah ada, kode berhenti tanpa menimpanya. Gunakan lokasi baru untuk reproduksi:

```bash
python 00_prepare_merge_dataset.py --merge --output '/home/aracel/Downloads/Skripsi/merge_dataset_reproduksi' --reference '/home/aracel/Downloads/Skripsi/all_data_merged(1).json'
```

Tidak perlu menghapus atau mengganti hasil lama. Kode tidak menjalankan tahap 01, 02, atau tahap berikutnya secara otomatis.

## Membaca hasil pembandingan

reference_comparison pada merge_report.json berisi pemeriksaan images, annotations, dan categories. Ketiganya harus true untuk menyatakan struktur metadata sama, termasuk nama berkas, urutan, ID, dimensi, bbox, dan atribut lain yang disimpan. Perbedaan spasi JSON dan urutan kunci objek tidak dianggap perbedaan; urutan entri list diperiksa.

Jika referensi berbeda, kode keluar dengan status 2 dan hasil tetap tersedia untuk pemeriksaan. Hasil tersebut jangan dipakai untuk mengganti masukan aktif tahap 01 dan seterusnya. Jika ada kegagalan baca/salin, keluaran parsial bukan dataset siap pakai; pilih direktori baru setelah masalah diselesaikan.

Kesamaan 40.344 gambar tidak cukup untuk membuktikan kesamaan dataset. Kesamaan metadata pun belum membuktikan kesamaan byte atau piksel gambar. Pengunduhan ulang dapat menghasilkan berkas berbeda, sehingga angka historis tidak dijamin dari unduhan baru. Kode tidak memotong, menggandakan, atau memanipulasi data untuk memaksakan angka tersebut.

## Aturan yang dipertahankan dan tambahan teknis

| Kondisi | Perilaku |
| --- | --- |
| Berkas gambar ditemukan | Disalin tanpa decode, crop, atau resize |
| Berkas gambar tidak ditemukan | Dilewati; anotasi yang merujuknya tidak disertakan |
| Kategori tidak dikenali | Anotasi dilewati; gambar yang tersalin tetap ada |
| Gambar tanpa anotasi | Tetap ada |
| Isi dua gambar identik | Keduanya tetap ada; belum deduplikasi |
| ID kategori sumber berbeda | Dipetakan melalui nama kategori |
| JSON suatu split tidak ada | Dilewati dan dicatat |
| Folder sumber ds01–ds10 tidak lengkap | Dihentikan agar sumber penelitian tidak diam-diam berubah |
| Folder keluaran sudah ada | Dihentikan untuk menjaga hasil lama |
| Nama keluaran bertabrakan atau ID gambar/kategori sumber tidak unik | Dihentikan, bukan menimpa atau membentuk relasi ambigu |

Tambahan validasi dan laporan tidak mengubah seleksi pada data sumber valid. Pembacaan JSON dilakukan satu kali per pelaksanaan, pemetaan kategori memakai dictionary, dan penghitungan anotasi memakai Counter. Penggabungan tidak menerapkan deduplikasi atau penyaringan gambar berdasarkan kelas. Program hanya mengolah uang; kandidat nonuang tidak digabung di sini.

## Hubungan dengan tahap 01 dan 02

Kode yang sudah ada membaca lokasi berikut:

| Hasil penggabungan | Lokasi masukan tahap persiapan lama |
| --- | --- |
| merge_dataset/all_images/ | /home/aracel/Downloads/Skripsi/persiapan_data/raw_dataset/uang/all_image/ |
| merge_dataset/all_data_merged.json | /home/aracel/Downloads/Skripsi/persiapan_data/raw_dataset/uang/all_data_merged.json |

Ada perbedaan all_images dan all_image. Penempatan ulang dapat memakai salinan berkas dengan nama internal tetap, atau pengaturan jalur masukan. Kode baru tidak menyalin otomatis ke lokasi aktif tersebut agar tidak mengubah dasar hasil penelitian yang sudah selesai. Memperbaiki dokumentasi tidak mewajibkan pengulangan tahap 01 dan seterusnya; penggantian isi data yang sebenarnya berbeda perlu dievaluasi dampaknya dan tidak dapat dianggap kompatibel hanya karena jumlah sama.

## Penempatan teks pada skripsi

Naskah_5_1_1_dan_5_1_2.docx berisi teks kedua subbab, tabel, gambar, serta tambahan lampiran. Bagian utama disisipkan sebelum judul lama “5.1.1 Implementasi Audit Dataset”. Jangan menimpa isi audit yang sudah ada. Lampiran A.1 dan C ditempatkan pada bagian lampiran, bukan di antara 5.1.2 dan audit.

Susunan baru:

| Nomor | Isi |
| --- | --- |
| 5.1.1 | Akuisisi dan Identifikasi Sumber Dataset |
| 5.1.2 | Implementasi Penggabungan Dataset Uang |
| 5.1.3 | Implementasi Audit Dataset |
| 5.1.4 | Implementasi Ekstraksi Area Uang |
| 5.1.5 | Implementasi Audit Visual |
| 5.1.6 | Implementasi Pengendalian Duplikasi Identik |
| 5.1.7 | Implementasi Pembentukan dan Pembagian Dataset |

Untuk versi Bab_5_1_Revisi_Lengkap_dan_Lampiran sebelumnya, ganti paragraf pembuka mulai “Persiapan dataset diimplementasikan mengikuti metode pada Subbab 3.4” sampai “…disajikan pada Tabel 5.1.” dengan paragraf berikut:

> Persiapan dataset diimplementasikan mengikuti metode pada Subbab 3.4. Rangkaian pekerjaan mencakup akuisisi dan identifikasi sumber, pemeriksaan kelas dan penggabungan dataset uang, audit struktur dataset, ekstraksi area uang, audit visual, pengendalian duplikasi identik, serta pembentukan dan pembagian dataset klasifikasi delapan kelas. Implementasi dijelaskan melalui sumber masukan, keputusan pemrosesan, artefak keluaran, dan jumlah sampel pada setiap tahap. Keterkaitan sembilan skrip dengan artefak utamanya disajikan pada Tabel 5.1.

Tambahkan satu baris pertama sebelum 01_audit_dataset.py pada Tabel 5.1:

| Skrip | Fungsi utama | Artefak utama |
| --- | --- | --- |
| 00_prepare_merge_dataset.py | Inventarisasi kelas dan penggabungan sepuluh sumber uang | Daftar kelas pada terminal; all_images; all_data_merged.json; merge_report.json pada skrip reproduksi |

Ganti kalimat awal subbab audit yang semula “Data yang digunakan mencakup sepuluh sumber citra uang dan satu sumber citra nonuang yang tercatat pada source_registry.csv.” menjadi:

> Data yang diaudit mencakup hasil penggabungan sepuluh sumber uang pada Subbab 5.1.2 dan kandidat citra nonuang yang asalnya dijelaskan pada Subbab 5.1.1.

## Penomoran tabel dan gambar

Panduan ini memakai penomoran versi revisi sebelumnya: Tabel 5.1 pemetaan skrip sudah ada. Lima tabel baru menjadi Tabel 5.2–5.6. Tabel lama bergeser sebagai berikut:

| Tabel lama | Tabel baru | Isi |
| --- | --- | --- |
| 5.2 | 5.7 | Audit awal |
| 5.3 | 5.8 | Ekstraksi |
| 5.4 | 5.9 | Audit visual |
| 5.5 | 5.10 | Deduplikasi |
| 5.6 | 5.11 | Komposisi delapan kelas |
| 5.7 | 5.12 | Distribusi pembagian final |

Gambar baru pada 5.1.2 adalah Gambar 5.1. Gambar lama 5.1–5.4 menjadi 5.2–5.5. Gambar baru rincian merge menjadi Gambar A.1; gambar lama A.1–A.6 menjadi A.2–A.7. Nomor subbagian Lampiran A ikut bergeser. Lampiran B lama tetap dipertahankan; daftar sumber ditambahkan sebagai Lampiran C. Terapkan perubahan melalui caption dan cross-reference Word lalu perbarui daftar tabel/gambar, bukan replace teks angka secara membabi buta.

Dokumen Word menyematkan dua gambar. Versi Markdown menyediakan penanda lokasi gambar untuk penyalinan teks. Gambar tersedia terpisah dalam PNG dan SVG; PNG siap dimasukkan, SVG dapat diedit. Tidak ada gambar uang sintetis yang dibuat.

## Validasi dan batas bukti

1. Menghitung ulang seluruh metadata historis dan mencocokkannya dengan CSV serta audit_summary.json.
2. Menjalankan uji sintetis untuk kategori null/0/75000, ID kategori 0 yang valid, gambar hilang, duplikasi isi, JSON split hilang, keluaran lama, dan pembandingan referensi.
3. Membandingkan keluaran uji sintetis dengan kode lama yang hanya diperbaiki salah nama penghitung anotasinya: hasil metadata sama.
4. Memainkan kembali metadata lengkap 40.344 citra dan 40.062 anotasi melalui fungsi merge dengan operasi berkas gambar disimulasikan: metadata keluaran sama dengan JSON historis. Uji ini memverifikasi penamaan, urutan dan penomoran; bukan reproduksi independen dari sepuluh dataset mentah, bukan pengujian piksel, dan bukan bukti ulang kategori sumber sebelum penyaringan.
5. Memeriksa kembali naskah, jumlah dalam tabel, rujukan gambar, dan hasil render Word.

Daftar kasus yang lulus serta SHA-256 JSON referensi tersedia dalam hasil_validasi.json. Seluruh dataset mentah dan foto asli belum tersedia di sini; kesamaan hasil pengunduhan ulang harus diperiksa ketika datanya tersedia. Tidak diperlukan rumus baru pada kedua subbab ini.
