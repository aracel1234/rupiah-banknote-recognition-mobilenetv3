# Rencana Pengumpulan Citra Statis

Aplikasi ini mengimplementasikan bagian **data citra statis** dari kalibrasi aplikasi.

Per perangkat:

| Kelompok | Komposisi | Jumlah |
|---|---|---:|
| Kualitas | 8 kelas × 3 kondisi cahaya × 2 kondisi fokus × 5 citra | 240 |
| ROI | 8 kelas × 3 jarak × 5 citra | 120 |
| **Total** | | **360 citra** |

Dua perangkat target menghasilkan **720 citra statis**.

Kelas: 1000, 2000, 5000, 10000, 20000, 50000, 100000, nonuang.

Kualitas:
- cahaya: redup, normal, terang;
- fokus: tajam, blur;
- 5 pengulangan.

ROI:
- jarak: 10, 20, 30 cm;
- 5 pengulangan;
- kandidat ROI 0,70 / 0,80 / 0,90 **tidak diambil sebagai tiga foto berbeda**. Ketiganya diturunkan dari full frame yang sama.

## Yang tidak dikumpulkan aplikasi ini

Kalibrasi urutan (40 urutan per perangkat) memerlukan skor inferensi frame-per-frame dan sebaiknya dikumpulkan melalui aplikasi pengenalan utama / mode logging khusus, bukan dipaksakan ke collector foto statis ini.
