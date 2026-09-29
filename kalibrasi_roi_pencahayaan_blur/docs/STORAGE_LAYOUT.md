# Struktur Penyimpanan

Penyimpanan lokal aplikasi menjadi sumber utama ketika capture dilakukan. Folder Google Drive yang dipilih melalui Android Storage Access Framework menjadi mirror/salinan.

```text
calibration/<device_alias>/
├── experiment_plan.json
├── checklist.json
├── checklist.csv
├── manifest.jsonl
├── manifest.csv
├── quality/
│   └── <class>/<lighting>/<focus>/<sample_id>/
│       ├── frame_rgb.png
│       ├── frame_luma.png
│       └── metadata.json
└── roi/
    └── <class>/<distance>/<sample_id>/
        ├── frame_rgb.png
        ├── frame_luma.png
        └── metadata.json
```

Drive mirror:

```text
<folder yang dipilih>/RupiahCalibrationCollector/<device_alias>/...
```

`frame_rgb.png` adalah serialisasi lossless dari frame ImageAnalysis yang telah dinormalisasi orientasinya menggunakan konversi limited-range BT.601 yang konsisten dengan aplikasi penelitian. `frame_luma.png` mempertahankan kanal Y untuk analisis luminansi/ketajaman. Tidak ada ROI, CLAHE, resize 224×224, atau inferensi sebelum penyimpanan.
