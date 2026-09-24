#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

# Kurangi log TensorFlow yang tidak diperlukan.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import pandas as pd
import tensorflow as tf


# ============================================================
# KONFIGURASI
# ============================================================

PROJECT_ROOT = Path("/home/aracel/Downloads/Skripsi")

ANDROID_MODEL_DIR = (
    PROJECT_ROOT
    / "implementasi_android"
    / "app"
    / "src"
    / "main"
    / "assets"
    / "model"
)

MODEL_PATH = ANDROID_MODEL_DIR / "model.tflite"
TENSOR_CONTRACT_PATH = ANDROID_MODEL_DIR / "tensor_contract.json"
CLASS_NAMES_PATH = ANDROID_MODEL_DIR / "class_names.json"

VALIDATION_ROOT = (
    PROJECT_ROOT
    / "laporan_skripsi"
    / "Aset Penulisan bab 5.6"
    / "Validasi Inferensi"
)

REFERENCE_MANIFEST_PATH = (
    VALIDATION_ROOT
    / "reference_manifest.csv"
)

REFERENCE_IMAGE_DIR = (
    VALIDATION_ROOT
    / "reference_images"
)

OUTPUT_PATH = (
    VALIDATION_ROOT
    / "python_predictions.csv"
)

SUMMARY_PATH = (
    VALIDATION_ROOT
    / "python_inference_summary.json"
)

NUM_THREADS = 4


# ============================================================
# UTILITAS
# ============================================================

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def load_json(path: Path):
    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def shape_to_text(shape) -> str:
    return "x".join(
        str(int(x))
        for x in shape
    )


def dtype_name(dtype) -> str:
    return np.dtype(dtype).name


# ============================================================
# VALIDASI ARTEFAK
# ============================================================

def validate_artifacts():
    required = [
        MODEL_PATH,
        TENSOR_CONTRACT_PATH,
        CLASS_NAMES_PATH,
        REFERENCE_MANIFEST_PATH,
        REFERENCE_IMAGE_DIR,
    ]

    for path in required:
        if not path.exists():
            raise FileNotFoundError(
                f"Artefak tidak ditemukan: {path}"
            )

    contract = load_json(
        TENSOR_CONTRACT_PATH
    )

    class_names = load_json(
        CLASS_NAMES_PATH
    )

    if not isinstance(class_names, list):
        raise RuntimeError(
            "class_names.json bukan list."
        )

    contract_classes = contract.get(
        "class_names"
    )

    if contract_classes != class_names:
        raise RuntimeError(
            "class_names.json tidak sama dengan "
            "class_names pada tensor_contract.json."
        )

    if len(class_names) != 8:
        raise RuntimeError(
            f"Diharapkan 8 kelas, "
            f"ditemukan {len(class_names)}."
        )

    actual_model_sha = sha256_file(
        MODEL_PATH
    )

    expected_model_sha = contract.get(
        "model_sha256"
    )

    if actual_model_sha != expected_model_sha:
        raise RuntimeError(
            "\nSHA-256 model tidak sesuai kontrak.\n"
            f"Expected : {expected_model_sha}\n"
            f"Actual   : {actual_model_sha}"
        )

    return (
        contract,
        class_names,
        actual_model_sha,
    )


# ============================================================
# LOAD & VALIDASI MANIFEST
# ============================================================

def load_reference_manifest(
    class_names: list[str],
) -> pd.DataFrame:

    df = pd.read_csv(
        REFERENCE_MANIFEST_PATH,
        dtype={
            "reference_id": str,
            "sample_id": str,
            "class_index": int,
            "label": str,
            "source_id": str,
            "reference_file": str,
            "sha256": str,
        },
    )

    required_columns = {
        "reference_id",
        "sample_id",
        "class_index",
        "label",
        "source_id",
        "reference_file",
        "sha256",
    }

    missing = (
        required_columns
        - set(df.columns)
    )

    if missing:
        raise RuntimeError(
            "Kolom reference_manifest tidak lengkap: "
            f"{sorted(missing)}"
        )

    if len(df) != 16:
        raise RuntimeError(
            f"Diharapkan 16 referensi, "
            f"ditemukan {len(df)}."
        )

    if df["reference_id"].nunique() != 16:
        raise RuntimeError(
            "reference_id tidak unik."
        )

    if df["sample_id"].nunique() != 16:
        raise RuntimeError(
            "sample_id tidak unik."
        )

    # Verifikasi mapping class_index -> label
    for row in df.itertuples(index=False):

        idx = int(row.class_index)

        if idx < 0 or idx >= len(class_names):
            raise RuntimeError(
                f"class_index tidak valid: {idx}"
            )

        expected_label = str(
            class_names[idx]
        )

        if str(row.label) != expected_label:
            raise RuntimeError(
                "\nMapping kelas tidak konsisten.\n"
                f"reference_id : {row.reference_id}\n"
                f"class_index  : {idx}\n"
                f"Manifest     : {row.label}\n"
                f"Contract     : {expected_label}"
            )

    return (
        df.sort_values("reference_id")
        .reset_index(drop=True)
    )


# ============================================================
# PREPROCESSING PYTHON
#
# Kontrak:
# - decode sebagai RGB
# - resize 224 x 224
# - bilinear
# - antialias = False
# - float32
# - nilai eksternal tetap [0,255]
#
# TIDAK dilakukan pembagian dengan 255.
# TIDAK digunakan preprocess_input MobileNetV3.
# ============================================================

def preprocess_image(
    image_path: Path,
    target_height: int,
    target_width: int,
) -> np.ndarray:

    raw = tf.io.read_file(
        str(image_path)
    )

    image = tf.io.decode_image(
        raw,
        channels=3,
        expand_animations=False,
    )

    image.set_shape(
        [None, None, 3]
    )

    # Ubah ke float32 tanpa normalisasi.
    image = tf.cast(
        image,
        tf.float32,
    )

    image = tf.image.resize(
        image,
        size=[
            target_height,
            target_width,
        ],
        method=tf.image.ResizeMethod.BILINEAR,
        antialias=False,
    )

    tensor = image.numpy().astype(
        np.float32,
        copy=False,
    )

    # Tambahkan batch dimension.
    tensor = np.expand_dims(
        tensor,
        axis=0,
    )

    return tensor


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 78)
    print("PYTHON REFERENCE INFERENCE - 16 CITRA")
    print("=" * 78)

    # --------------------------------------------------------
    # 1. Validasi aset
    # --------------------------------------------------------

    (
        contract,
        class_names,
        model_sha,
    ) = validate_artifacts()

    manifest = load_reference_manifest(
        class_names
    )

    print("\nModel:")
    print(f"  Path    : {MODEL_PATH}")
    print(f"  SHA-256 : {model_sha}")
    print(
        f"  Candidate: "
        f"{contract.get('candidate')}"
    )

    print("\nClasses:")

    for i, name in enumerate(class_names):
        print(f"  {i}: {name}")

    # --------------------------------------------------------
    # 2. Buat interpreter TFLite
    # --------------------------------------------------------

    interpreter = tf.lite.Interpreter(
        model_path=str(MODEL_PATH),
        num_threads=NUM_THREADS,
    )

    interpreter.allocate_tensors()

    input_details = (
        interpreter.get_input_details()
    )

    output_details = (
        interpreter.get_output_details()
    )

    if len(input_details) != 1:
        raise RuntimeError(
            "Model harus mempunyai tepat "
            "satu input tensor."
        )

    if len(output_details) != 1:
        raise RuntimeError(
            "Model harus mempunyai tepat "
            "satu output tensor."
        )

    inp = input_details[0]
    out = output_details[0]

    input_shape = [
        int(x)
        for x in inp["shape"]
    ]

    output_shape = [
        int(x)
        for x in out["shape"]
    ]

    input_dtype = dtype_name(
        inp["dtype"]
    )

    output_dtype = dtype_name(
        out["dtype"]
    )

    print("\nRuntime tensor contract:")
    print(
        f"  Input shape  : {input_shape}"
    )
    print(
        f"  Input dtype  : {input_dtype}"
    )
    print(
        f"  Output shape : {output_shape}"
    )
    print(
        f"  Output dtype : {output_dtype}"
    )

    # --------------------------------------------------------
    # 3. Verifikasi kontrak runtime terhadap JSON
    # --------------------------------------------------------

    expected_input_shape = [
        int(x)
        for x in contract["input_shape"]
    ]

    expected_output_shape = [
        int(x)
        for x in contract["output_shape"]
    ]

    if input_shape != expected_input_shape:
        raise RuntimeError(
            "\nInput shape tidak sesuai contract.\n"
            f"JSON    : {expected_input_shape}\n"
            f"Runtime : {input_shape}"
        )

    if output_shape != expected_output_shape:
        raise RuntimeError(
            "\nOutput shape tidak sesuai contract.\n"
            f"JSON    : {expected_output_shape}\n"
            f"Runtime : {output_shape}"
        )

    if (
        input_dtype
        != str(contract["input_dtype"])
    ):
        raise RuntimeError(
            "\nInput dtype tidak sesuai contract.\n"
            f"JSON    : {contract['input_dtype']}\n"
            f"Runtime : {input_dtype}"
        )

    if (
        output_dtype
        != str(contract["output_dtype"])
    ):
        raise RuntimeError(
            "\nOutput dtype tidak sesuai contract.\n"
            f"JSON    : {contract['output_dtype']}\n"
            f"Runtime : {output_dtype}"
        )

    if input_shape != [1, 224, 224, 3]:
        raise RuntimeError(
            "Script saat ini hanya menerima "
            "kontrak [1,224,224,3]."
        )

    if input_dtype != "float32":
        raise RuntimeError(
            "Script baseline ini mengharapkan "
            "input float32."
        )

    if output_dtype != "float32":
        raise RuntimeError(
            "Script baseline ini mengharapkan "
            "output float32."
        )

    if output_shape != [1, 8]:
        raise RuntimeError(
            "Script baseline ini mengharapkan "
            "output [1,8]."
        )

    # --------------------------------------------------------
    # 4. Warm-up
    # --------------------------------------------------------

    dummy = np.zeros(
        input_shape,
        dtype=np.float32,
    )

    interpreter.set_tensor(
        inp["index"],
        dummy,
    )

    interpreter.invoke()

    # --------------------------------------------------------
    # 5. Inferensi 16 citra
    # --------------------------------------------------------

    output_rows = []

    print("\n" + "-" * 78)
    print("HASIL INFERENSI")
    print("-" * 78)

    for row in manifest.itertuples(
        index=False
    ):

        reference_id = str(
            row.reference_id
        )

        image_path = (
            REFERENCE_IMAGE_DIR
            / str(row.reference_file)
        )

        result = {
            "reference_id": reference_id,
            "sample_id": str(row.sample_id),
            "true_class_index": int(
                row.class_index
            ),
            "true_label": str(row.label),
            "source_id": str(row.source_id),
            "reference_file": str(
                row.reference_file
            ),
            "processing_success": False,
            "error_message": "",
            "model_sha256": model_sha,
            "input_shape": (
                shape_to_text(input_shape)
            ),
            "input_dtype": input_dtype,
            "output_shape": (
                shape_to_text(output_shape)
            ),
            "output_dtype": output_dtype,
            "top_index": "",
            "top_label": "",
            "top_score": "",
            "score_sum": "",
            "preprocess_ms": "",
            "inference_ms": "",
        }

        for i in range(8):
            result[f"score_{i}"] = ""

        try:
            if not image_path.is_file():
                raise FileNotFoundError(
                    f"Citra tidak ditemukan: "
                    f"{image_path}"
                )

            # --------------------------------------------
            # Verifikasi SHA citra
            # --------------------------------------------

            actual_image_sha = sha256_file(
                image_path
            )

            expected_image_sha = str(
                row.sha256
            ).lower()

            if (
                actual_image_sha.lower()
                != expected_image_sha
            ):
                raise RuntimeError(
                    "SHA-256 citra tidak sesuai "
                    "reference_manifest.csv."
                )

            result["image_sha256"] = (
                actual_image_sha
            )

            # --------------------------------------------
            # Preprocess
            # --------------------------------------------

            t0 = time.perf_counter_ns()

            input_tensor = preprocess_image(
                image_path=image_path,
                target_height=input_shape[1],
                target_width=input_shape[2],
            )

            t1 = time.perf_counter_ns()

            # --------------------------------------------
            # Validasi tensor input
            # --------------------------------------------

            if (
                list(input_tensor.shape)
                != input_shape
            ):
                raise RuntimeError(
                    "Shape tensor hasil preprocessing "
                    f"salah: {input_tensor.shape}"
                )

            if (
                input_tensor.dtype
                != np.float32
            ):
                raise RuntimeError(
                    "Tensor input bukan float32."
                )

            # Rentang eksternal harus tetap [0,255].
            input_min = float(
                np.min(input_tensor)
            )

            input_max = float(
                np.max(input_tensor)
            )

            if input_min < 0.0:
                raise RuntimeError(
                    f"Input minimum < 0: {input_min}"
                )

            if input_max > 255.0:
                raise RuntimeError(
                    f"Input maksimum > 255: {input_max}"
                )

            result["input_min"] = (
                f"{input_min:.9f}"
            )

            result["input_max"] = (
                f"{input_max:.9f}"
            )

            # --------------------------------------------
            # Inferensi
            # --------------------------------------------

            interpreter.set_tensor(
                inp["index"],
                input_tensor,
            )

            t2 = time.perf_counter_ns()

            interpreter.invoke()

            t3 = time.perf_counter_ns()

            scores = interpreter.get_tensor(
                out["index"]
            )[0].astype(
                np.float32,
                copy=False,
            )

            if scores.shape != (8,):
                raise RuntimeError(
                    "Output skor bukan 8 elemen: "
                    f"{scores.shape}"
                )

            if not np.all(
                np.isfinite(scores)
            ):
                raise RuntimeError(
                    "Output mengandung NaN/Inf."
                )

            top_index = int(
                np.argmax(scores)
            )

            top_label = str(
                class_names[top_index]
            )

            top_score = float(
                scores[top_index]
            )

            score_sum = float(
                np.sum(scores)
            )

            preprocess_ms = (
                t1 - t0
            ) / 1_000_000.0

            inference_ms = (
                t3 - t2
            ) / 1_000_000.0

            result[
                "processing_success"
            ] = True

            result["top_index"] = (
                top_index
            )

            result["top_label"] = (
                top_label
            )

            result["top_score"] = (
                f"{top_score:.9f}"
            )

            result["score_sum"] = (
                f"{score_sum:.9f}"
            )

            result["preprocess_ms"] = (
                f"{preprocess_ms:.3f}"
            )

            result["inference_ms"] = (
                f"{inference_ms:.3f}"
            )

            for i, score in enumerate(
                scores
            ):
                result[f"score_{i}"] = (
                    f"{float(score):.9f}"
                )

            status = (
                "BENAR"
                if top_label
                == str(row.label)
                else "SALAH"
            )

            print(
                f"{reference_id:<8} "
                f"true={str(row.label):<8} "
                f"pred={top_label:<8} "
                f"score={top_score:.6f} "
                f"[{status}]"
            )

        except Exception as exc:

            result["error_message"] = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            print(
                f"{reference_id:<8} "
                f"ERROR: "
                f"{result['error_message']}"
            )

        output_rows.append(result)

    # --------------------------------------------------------
    # 6. Simpan CSV
    # --------------------------------------------------------

    result_df = pd.DataFrame(
        output_rows
    )

    fixed_columns = [
        "reference_id",
        "sample_id",
        "true_class_index",
        "true_label",
        "source_id",
        "reference_file",
        "image_sha256",
        "processing_success",
        "error_message",
        "model_sha256",
        "input_shape",
        "input_dtype",
        "input_min",
        "input_max",
        "output_shape",
        "output_dtype",
        "top_index",
        "top_label",
        "top_score",
        "score_sum",
    ]

    score_columns = [
        f"score_{i}"
        for i in range(8)
    ]

    timing_columns = [
        "preprocess_ms",
        "inference_ms",
    ]

    for col in (
        fixed_columns
        + score_columns
        + timing_columns
    ):
        if col not in result_df.columns:
            result_df[col] = ""

    result_df = result_df[
        fixed_columns
        + score_columns
        + timing_columns
    ]

    result_df.to_csv(
        OUTPUT_PATH,
        index=False,
        quoting=csv.QUOTE_MINIMAL,
    )

    # --------------------------------------------------------
    # 7. Ringkasan
    # --------------------------------------------------------

    success_series = (
        result_df["processing_success"]
        .astype(str)
        .str.lower()
        .eq("true")
    )

    success_count = int(
        success_series.sum()
    )

    failed_count = int(
        len(result_df)
        - success_count
    )

    correct_count = int(
        (
            success_series
            & (
                result_df["top_label"]
                .astype(str)
                == result_df[
                    "true_label"
                ].astype(str)
            )
        ).sum()
    )

    summary = {
        "schema_version": 1,
        "purpose": (
            "Python baseline for Android "
            "integration equivalence validation"
        ),
        "reference_count": int(
            len(result_df)
        ),
        "processing_success_count": (
            success_count
        ),
        "processing_failed_count": (
            failed_count
        ),
        "ground_truth_top1_match_count": (
            correct_count
        ),
        "ground_truth_top1_match_rate": (
            correct_count
            / success_count
            if success_count > 0
            else None
        ),
        "model_path": str(
            MODEL_PATH
        ),
        "model_sha256": model_sha,
        "candidate": contract.get(
            "candidate"
        ),
        "num_threads": NUM_THREADS,
        "input_shape": input_shape,
        "input_dtype": input_dtype,
        "input_external_range": [
            0,
            255,
        ],
        "resize": "bilinear",
        "antialias": False,
        "output_shape": output_shape,
        "output_dtype": output_dtype,
        "class_names": class_names,
        "tensorflow_version": (
            tf.__version__
        ),
        "python_version": (
            platform.python_version()
        ),
        "platform": platform.platform(),
        "note": (
            "Top-1 terhadap ground truth dicatat "
            "sebagai informasi tambahan. "
            "Kriteria utama validasi integrasi "
            "adalah kesesuaian hasil Python "
            "dengan hasil Android untuk citra "
            "referensi yang sama."
        ),
    }

    with SUMMARY_PATH.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            summary,
            f,
            indent=2,
            ensure_ascii=False,
        )

        f.write("\n")

    # --------------------------------------------------------
    # 8. Hasil akhir terminal
    # --------------------------------------------------------

    print("\n" + "=" * 78)
    print("RINGKASAN")
    print("=" * 78)

    print(
        f"Reference images       : "
        f"{len(result_df)}"
    )

    print(
        f"Processing success     : "
        f"{success_count}"
    )

    print(
        f"Processing failed      : "
        f"{failed_count}"
    )

    print(
        f"Top-1 vs ground truth  : "
        f"{correct_count}/{success_count}"
    )

    print("\nOutput:")
    print(
        f"  Predictions : {OUTPUT_PATH}"
    )
    print(
        f"  Summary     : {SUMMARY_PATH}"
    )

    # Script dianggap gagal jika ada citra
    # yang tidak dapat diproses.
    if failed_count > 0:
        raise SystemExit(1)

    print(
        "\nSTATUS: seluruh 16 citra "
        "berhasil diproses."
    )


if __name__ == "__main__":
    main()