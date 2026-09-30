# Finalisasi Konfigurasi Operasional

Folder script yang disarankan:

`/home/aracel/Downloads/Skripsi/scripts/finalisasi_konfigurasi_operasional`

Output:

`/home/aracel/Downloads/Skripsi/hasil_konfigurasi_operasional`

Tahap ini menggabungkan hasil kalibrasi kualitas statis dengan hasil kalibrasi sequence.
Script **tidak mengubah proyek Android**. Ia hanya memverifikasi rantai bukti dan
menghasilkan konfigurasi final serta kandidat `app_config.json` final.

## Validasi

```bash
python 12_finalize_operational_config.py \
  --static-dir /home/aracel/Downloads/Skripsi/hasil_roi_annotation/08_static_quality_lock \
  --sequence-audit-dir /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/09_sequence_input_audit \
  --postinfer-dir /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/10_postinference_calibration \
  --android /home/aracel/Downloads/Skripsi/implementasi_android \
  --out /home/aracel/Downloads/Skripsi/hasil_konfigurasi_operasional \
  --validate-only
```

Output validasi yang diharapkan:

`VALIDATION_STATUS=READY_FOR_OPERATIONAL_LOCK`

## Eksekusi penuh

Jalankan perintah yang sama tanpa `--validate-only`.

Keluaran:

- `operational_config.json`
- `operational_selection_summary.json`
- `android_app_config_final.json`
- `operational_config_lock.json`

Konfigurasi yang diharapkan dari bukti saat ini:

- `analysis_fps = 3`
- `confidence_threshold = 0.65`
- `temporal_window_ms = 1500`
- `minimum_results = 3`

Script akan berhenti bila artefak Stage 8, Stage 09, Stage 10, atau source Android
berubah setelah proses kalibrasi.
