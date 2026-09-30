# Pengujian Bab 6

Folder ini memisahkan metadata/protokol kecil dari bukti mentah berukuran besar.

## Status sebelum pengujian formal
1. Terapkan patch instrumentasi Bab 6 pada `implementasi_android`.
2. Build bersih APK `app-arm64-v8a-debug.apk`.
3. Jalankan `tools/11_finalize_artifacts.py --apk <path APK ARM64>` dan salin hasil baru ke `00_identity/artifact/`.
4. Buat `test_apk_sha256.txt` dari APK ARM64 hasil build tersebut.
5. Lengkapi `emission_year` untuk 21 objek uang pada `00_identity/objects/banknote_manifest.csv`.
6. Isi nama + versi aplikasi lux meter pada `test_configuration.json`.
7. Konfirmasi fixture tetap yang masih berstatus PROPOSED pada `test_plan_lock.json`.
8. Setelah semua lengkap, ubah status `test_configuration.json` menjadi `ready_for_testing` dan `test_plan_lock.json` menjadi `bab6_test_plan_locked`, lalu hitung SHA-256 keduanya.

## Aturan validitas
- VALID-PASS: prosedur valid, keluaran sesuai.
- VALID-FAIL: prosedur valid, keluaran tidak sesuai. Tetap dihitung sebagai data penelitian.
- INVALID: prosedur melanggar protokol. Tidak digunakan untuk menilai sistem dan harus diulang dengan ID baru.
- RETEST: eksekusi baru yang menunjuk `retest_of`; record lama tidak ditimpa.

## Jumlah
`manifest_master.csv` berisi 706 baris eksekusi: 700 observasi utama + 6 warm-up latensi yang tidak masuk analisis.

## Data mentah
Log aplikasi, video, screenshot, APK, dan hasil mentah disimpan lokal dan diabaikan Git sesuai `.gitignore`. Metadata, manifest, skrip analisis, dan tabel ringkasan dapat disimpan di Git.
