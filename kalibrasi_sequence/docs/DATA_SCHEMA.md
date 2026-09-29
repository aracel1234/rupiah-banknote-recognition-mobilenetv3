# Data schema

## frames.csv

Satu baris mewakili satu frame yang dipilih oleh throttle target 5 FPS.

Kolom utama:

- `frame_index`, `elapsed_ms`: urutan dan waktu monotonik relatif terhadap awal sequence;
- `stage_id`, `expected_label`, `analysis_role`: ground truth terjadwal;
- `quality_pass`, `quality_code`: status gate kualitas;
- `luma_mean_original`, `luma_mean_processed`, `laplacian_variance`, `clahe_applied`;
- `score_*`: delapan skor Softmax, kosong bila frame ditolak quality gate;
- `top_label`, `top_score`;
- `preprocess_ms`, `inference_ms`, `pipeline_ms`.

## Ground truth stage

`analysis_role`:

- `target`: objek nominal target;
- `nonmoney`: objek nonuang;
- `reset`: ROI kosong atau nonuang yang digunakan untuk reset;
- `transition`: masa pergantian langsung, tidak dipakai sebagai endpoint benar/salah.

Analisis Python memberi guard 300 ms setelah perubahan stage untuk mengurangi kontaminasi waktu reaksi operator terhadap cue.
