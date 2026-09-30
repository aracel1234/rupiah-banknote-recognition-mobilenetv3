#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="/home/aracel/Downloads/Skripsi/scripts/kalibrasi_sequence"
POCO="/home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/poco"
REDMI="/home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/redmi_4x_santoni"
ANDROID="/home/aracel/Downloads/Skripsi/implementasi_android"
OUT_ROOT="/home/aracel/Downloads/Skripsi/kalibrasi_sequence_output/hasil_kalibrasi_sequence"

mkdir -p "$OUT_ROOT/09_sequence_input_audit"
mkdir -p "$OUT_ROOT/10_postinference_calibration"

python "$SCRIPT_DIR/09_validate_sequence_inputs.py" \
  --poco "$POCO" \
  --redmi "$REDMI" \
  --android "$ANDROID" \
  --plan "$SCRIPT_DIR/analysis_plan.json" \
  --out "$OUT_ROOT/09_sequence_input_audit"

python "$SCRIPT_DIR/10_replay_and_select_postinference.py" \
  --poco "$POCO" \
  --redmi "$REDMI" \
  --input-audit-dir "$OUT_ROOT/09_sequence_input_audit" \
  --plan "$SCRIPT_DIR/analysis_plan.json" \
  --out "$OUT_ROOT/10_postinference_calibration"

python "$SCRIPT_DIR/11_verify_sequence_calibration.py" \
  --result-dir "$OUT_ROOT/10_postinference_calibration"
