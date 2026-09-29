# Persiapan Analisis ROI Subbab 5.7.2

Paket ini menyiapkan **anotasi batas objek uang secara post-hoc** dari 210 citra ROI nominal (7 nominal × 3 jarak × 5 repetisi × 2 perangkat). Data mentah tidak dimodifikasi.

## Prinsip penelitian

1. `poco.zip` dan `redmi.zip` diperlakukan sebagai input mentah yang tidak diubah.
2. Anotasi otomatis hanya **proposal awal**. Semua 210 citra nominal wajib diperiksa manusia.
3. Jika uang tidak sepenuhnya terlihat di full frame, tandai `SOURCE_TRUNCATED`. Sampel tersebut otomatis tidak memenuhi ketercakupan penuh pada kandidat ROI mana pun.
4. Untuk citra yang sumbernya lengkap, batas uang direpresentasikan oleh empat titik sudut (quadrilateral), bukan bounding box axis-aligned.
5. Geometri kandidat ROI mengikuti kode Android `RoiGeometry.kt` secara identik:

```text
w = min(width × r, height × 0.90 × aspect)
h = w / aspect
ROI diletakkan di tengah frame
```

Dengan `aspect = 1.3420920964096548` dan `r ∈ {0.70, 0.80, 0.90}`.

6. Aturan ketercakupan: semua empat titik uang harus berada di dalam ROI.
7. Aturan latar operasional yang dikunci sebelum seleksi hasil: jika uang lengkap di ROI tetapi `banknote_occupancy < 0.50`, kandidat ditandai memiliki latar berlebih untuk sampel tersebut.
8. Kelas `nonuang` tidak diberi anotasi batas objek. Kelas tersebut tetap digunakan nanti saat menghitung macro F1 delapan kelas.
9. Output geometris **belum memilih ROI final**. Sesuai skripsi, urutan keputusan tetap: (1) ketercakupan uang, (2) macro F1, (3) proporsi latar.

## 1. Instal dependensi

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Siapkan draft otomatis

```bash
python 01_prepare_roi_annotation.py \
  --poco-zip /path/poco.zip \
  --redmi-zip /path/redmi.zip \
  --out hasil_roi_annotation
```

Salin `config.json` ke folder hasil:

```bash
cp config.json hasil_roi_annotation/config.json
```

Output penting:

```text
hasil_roi_annotation/
├── _extracted/                         # copy hasil ekstraksi ZIP
├── review_images/                      # salinan 210 RGB nominal untuk proses review
├── draft_overlays/                     # visual proposal otomatis
├── roi_object_annotations_draft.csv    # 210 baris
└── prepare_summary.json
```

## 3. Audit manual 210 citra

```bash
python 02_review_roi_annotation.py --work-dir hasil_roi_annotation
```

Kontrol:

```text
A       terima polygon otomatis
R       gambar ulang, klik 4 sudut uang lalu Enter
T       uang terpotong oleh batas full frame (SOURCE_TRUNCATED)
S       lewati sementara
B       kembali satu sampel
Q/ESC   simpan dan keluar
```

Klik sudut boleh dimulai dari sudut mana pun. Program mengurutkannya secara konsisten.

Hasil disimpan setelah setiap keputusan ke:

```text
roi_object_annotations_reviewed.csv
```

## 4. Finalisasi bukti geometri

Hanya jalankan setelah tidak ada `PENDING`:

```bash
python 03_finalize_roi_geometry.py --work-dir hasil_roi_annotation
```

Output:

```text
roi_geometric_metrics.csv
roi_geometric_summary.csv
roi_geometric_by_device_distance.csv
roi_geometry_lock.json
```

`03_finalize_roi_geometry.py` sengaja berhenti jika ada satu saja anotasi yang belum selesai diperiksa.

## Setelah tahap ini

Jangan langsung memilih ROI hanya dari `roi_geometric_summary.csv`. Tahap berikutnya harus menjalankan model final Dynamic Range terhadap crop kandidat 0.70, 0.80, dan 0.90 untuk memperoleh macro F1 delapan kelas. Hanya setelah itu urutan prioritas skripsi dapat diterapkan secara utuh.
