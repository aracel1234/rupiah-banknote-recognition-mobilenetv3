# Kalibrasi Sequence 5.7.3

Paket ini digunakan setelah dua dataset sequence sudah selesai dan lolos audit:

- POCO: `/home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/poco`
- Redmi 4X: `/home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/redmi_4x_santoni`

Script ditempatkan di:

`/home/aracel/Downloads/Skripsi/scripts/kalibrasi_sequence`

Output ditulis ke folder terpisah:

`/home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence`

## Prinsip analisis

`analysis_plan.json` adalah aturan seleksi yang dibekukan sebelum tabel hasil kandidat digunakan untuk memilih konfigurasi. Jangan mengubah file ini setelah Stage 09 dijalankan.

Tahapan:

1. **Stage 09** memverifikasi kembali dua dataset, source Android, dan memilih kandidat laju analisis tertinggi yang masih memenuhi `f_max = floor(1000/P95_pipeline)` pada **kedua** perangkat.
2. **Stage 10** mereplay seluruh sequence menggunakan semantik `TemporalDecision.kt`, menguji threshold 0,50–0,95 dan window 1000/1500/2000 ms, menjalankan bootstrap 2000 iterasi, quality gate MSSR satu-SE, lalu seleksi leksikografis yang sudah dipra-tetapkan.
3. **Stage 11** memverifikasi SHA-256 seluruh artefak hasil sebelum ZIP dikirim untuk audit.

Replay 3 FPS dari stream koleksi 5 FPS menggunakan throttle greedy yang mengikuti bentuk keputusan `RecognitionSession`: frame pertama dipakai, lalu frame berikutnya dipakai apabila selisih waktunya sekurang-kurangnya `ceil(1000/FPS)` ms dari frame replay sebelumnya.

## Struktur output

```text
/home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/
├── 09_sequence_input_audit/
│   ├── sequence_inventory.csv
│   ├── fps_capacity_by_device.csv
│   ├── sequence_input_audit.json
│   └── sequence_input_lock.json
│
└── 10_postinference_calibration/
    ├── frame_level_youden.csv
    ├── frame_level_youden_summary.json
    ├── candidate_metrics.csv
    ├── target_episode_outcomes.csv
    ├── nonmoney_episode_outcomes.csv
    ├── reset_stage_diagnostics.csv
    ├── direct_transition_diagnostics.csv
    ├── sequence_success_results.csv
    ├── per_class_car.csv
    ├── scenario_success_rates.csv
    ├── bootstrap_mssr_summary.csv
    ├── postinference_selection_decision.json
    └── postinference_calibration_lock.json
```

## Menjalankan bertahap

Masuk ke folder script:

```bash
cd /home/aracel/Downloads/Skripsi/scripts/kalibrasi_sequence

```

### Stage 09

```bash
python 09_validate_sequence_inputs.py \
  --poco /home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/poco \
  --redmi /home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/redmi_4x_santoni \
  --android /home/aracel/Downloads/Skripsi/implementasi_android \
  --plan /home/aracel/Downloads/Skripsi/scripts/kalibrasi_sequence/analysis_plan.json \
  --out /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/09_sequence_input_audit
```

Output akhir yang diharapkan:

```text
VALIDATION_STATUS=READY_FOR_POSTINFERENCE_REPLAY
```

### Stage 10

Hanya jalankan setelah Stage 09 berhasil:

```bash
python 10_replay_and_select_postinference.py \
  --poco /home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/poco \
  --redmi /home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/redmi_4x_santoni \
  --input-audit-dir /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/09_sequence_input_audit \
  --plan /home/aracel/Downloads/Skripsi/scripts/kalibrasi_sequence/analysis_plan.json \
  --out /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/10_postinference_calibration
```

Output akhir yang diharapkan:

```text
SELECTION_STATUS=POSTINFERENCE_CONFIGURATION_SELECTED
```

### Stage 11

```bash
python 11_verify_sequence_calibration.py \
  --result-dir /home/aracel/Downloads/Skripsi/hasil_kalibrasi_sequence/10_postinference_calibration
```

Output akhir yang diharapkan:

```text
OUTPUT_HASH_STATUS=OK
REVIEW_STATUS=READY_TO_SEND_FOR_AUDIT
```

## Menjalankan sekaligus

`run_all.sh` sudah berisi path yang diberikan pengguna:

```bash
chmod +x run_all.sh
./run_all.sh
```

## Setelah selesai

Jangan mengubah file hasil. Kompres seluruh folder:

```bash
cd /home/aracel/Downloads/Skripsi
zip -r hasil_kalibrasi_sequence.zip hasil_kalibrasi_sequence
```

Kirim ZIP tersebut untuk audit sebelum parameter dipindahkan ke `app_config.json` aplikasi utama atau sebelum narasi 5.7.3 disusun.
