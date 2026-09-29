#!/usr/bin/env python3
"""Stage 4 ROI model evaluation for thesis section 5.7.2.

Purpose
-------
Evaluate the three ROI width fractions (0.70, 0.80, 0.90) with the exact
locked Dynamic Range TFLite model after geometric ROI review is complete.

Important methodological boundary
---------------------------------
This script intentionally DOES NOT apply blur rejection, lighting rejection,
CLAHE, confidence thresholding, or temporal smoothing. Those are downstream
parameters and are not allowed to affect ROI model comparison.

Input preprocessing mirrors the fixed Android path as closely as the stored
calibration evidence permits:
  stored lossless RGB calibration frame -> centered ROI -> exact half-pixel
  bilinear resize to 224x224 -> float32 values in [0,255] -> TFLite model.

The calibration collector stores RGB as lossless PNG after orientation
normalization from the same YUV_420_888 frame. The PNG is therefore the locked
offline evidence used here; raw U/V planes were not serialized.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import zipfile

import numpy as np
import pandas as pd
from PIL import Image

LABELS_EXPECTED = ["1000", "2000", "5000", "10000", "20000", "50000", "100000", "nonuang"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def find_unique_suffix(names: list[str], suffix: str) -> str:
    hits = [n for n in names if n.endswith(suffix)]
    if len(hits) != 1:
        raise RuntimeError(f"Expected exactly one '*{suffix}' in ZIP, found {len(hits)}: {hits[:5]}")
    return hits[0]


def find_unique_file_suffix(root: Path, suffix: str) -> Path:
    hits = [p for p in root.rglob("*") if p.is_file() and p.as_posix().endswith(suffix)]
    if len(hits) != 1:
        raise RuntimeError(
            f"Expected exactly one '*{suffix}' under {root}, found {len(hits)}: "
            f"{[str(x) for x in hits[:5]]}"
        )
    return hits[0]


def load_android_bundle(android_source: Path) -> dict:
    """Load the Android artifacts from either a project directory or a ZIP archive."""
    wanted = {
        "model.tflite": "app/src/main/assets/model/model.tflite",
        "class_names.json": "app/src/main/assets/model/class_names.json",
        "tensor_contract.json": "app/src/main/assets/model/tensor_contract.json",
        "model_identity.json": "app/src/main/assets/model/model_identity.json",
        "selection_lock.json": "app/src/main/assets/model/selection_lock.json",
        "asset_integrity.json": "app/src/main/assets/model/asset_integrity.json",
        "app_config.json": "app/src/main/assets/app_config.json",
        "RoiGeometry.kt": "app/src/main/java/id/ac/ub/rupiah/image/RoiGeometry.kt",
        "FramePreprocessor.kt": "app/src/main/java/id/ac/ub/rupiah/image/FramePreprocessor.kt",
        "ModelRunner.kt": "app/src/main/java/id/ac/ub/rupiah/inference/ModelRunner.kt",
    }

    data = {}
    archive_paths = {}
    source_type = "directory" if android_source.is_dir() else "zip"

    if android_source.is_dir():
        for key, suffix in wanted.items():
            path = find_unique_file_suffix(android_source, suffix)
            archive_paths[key] = str(path.relative_to(android_source))
            data[key] = path.read_bytes()
    elif android_source.is_file() and zipfile.is_zipfile(android_source):
        with zipfile.ZipFile(android_source, "r") as z:
            names = z.namelist()
            for key, suffix in wanted.items():
                name = find_unique_suffix(names, suffix)
                archive_paths[key] = name
                data[key] = z.read(name)
    else:
        raise RuntimeError(f"Android source must be a directory or ZIP: {android_source}")

    integrity = json.loads(data["asset_integrity.json"])
    for name in ["model.tflite", "class_names.json", "tensor_contract.json", "model_identity.json", "selection_lock.json"]:
        actual = sha256_bytes(data[name])
        expected = integrity.get(name)
        if actual != expected:
            raise RuntimeError(f"Android asset integrity mismatch for {name}: {actual} != {expected}")

    labels = json.loads(data["class_names.json"])
    contract = json.loads(data["tensor_contract.json"])
    identity = json.loads(data["model_identity.json"])
    lock = json.loads(data["selection_lock.json"])
    app_config = json.loads(data["app_config.json"])
    model_sha = sha256_bytes(data["model.tflite"])

    if labels != LABELS_EXPECTED:
        raise RuntimeError(f"Unexpected class order: {labels}")
    if contract.get("class_names") != LABELS_EXPECTED:
        raise RuntimeError("tensor_contract class order differs from class_names.json")
    if contract.get("input_shape") != [1, 224, 224, 3] or contract.get("output_shape") != [1, 8]:
        raise RuntimeError("Unexpected model tensor shapes")
    if contract.get("input_dtype") != "float32" or contract.get("output_dtype") != "float32":
        raise RuntimeError("Expected float32 model interface")
    if identity.get("candidate") != "dynamic_range" or lock.get("selected_candidate") != "dynamic_range":
        raise RuntimeError("Expected locked candidate dynamic_range")
    for source_name, source_value in [
        ("model_identity", identity.get("sha256")),
        ("tensor_contract", contract.get("model_sha256")),
        ("selection_lock", lock.get("model_sha256")),
    ]:
        if source_value != model_sha:
            raise RuntimeError(f"Model hash mismatch against {source_name}")

    return {
        "raw": data,
        "archive_paths": archive_paths,
        "labels": labels,
        "contract": contract,
        "identity": identity,
        "selection_lock": lock,
        "app_config": app_config,
        "model_sha256": model_sha,
        "source_type": source_type,
        "source_path": str(android_source.resolve()),
        "source_hashes": {
            "RoiGeometry.kt": sha256_bytes(data["RoiGeometry.kt"]),
            "FramePreprocessor.kt": sha256_bytes(data["FramePreprocessor.kt"]),
            "ModelRunner.kt": sha256_bytes(data["ModelRunner.kt"]),
            "app_config.json": sha256_bytes(data["app_config.json"]),
            "model.tflite": model_sha,
        },
    }


def read_geometry(geometry_dir: Path) -> dict:
    required = [
        "roi_object_annotations_reviewed.csv",
        "roi_geometric_metrics.csv",
        "roi_geometric_summary.csv",
        "roi_geometric_by_device_distance.csv",
        "roi_geometry_lock.json",
    ]
    for name in required:
        if not (geometry_dir / name).is_file():
            raise FileNotFoundError(f"Missing geometry artifact: {geometry_dir / name}")

    lock = json.loads((geometry_dir / "roi_geometry_lock.json").read_text(encoding="utf-8"))
    if lock.get("status") != "geometry_annotation_complete":
        raise RuntimeError("Geometry lock is not complete")
    if int(lock.get("reviewed_nominal_samples", -1)) != 210:
        raise RuntimeError("Expected 210 reviewed nominal ROI samples")
    annotation_sha = sha256_file(geometry_dir / "roi_object_annotations_reviewed.csv")
    if annotation_sha != lock.get("annotation_csv_sha256"):
        raise RuntimeError("Reviewed annotation CSV hash does not match roi_geometry_lock.json")

    candidates = [float(x) for x in lock.get("candidate_fractions", [])]
    if candidates != [0.7, 0.8, 0.9]:
        raise RuntimeError(f"Unexpected ROI candidates: {candidates}")

    summary = pd.read_csv(geometry_dir / "roi_geometric_summary.csv")
    if set(np.round(summary["candidate_roi_width_fraction"].astype(float), 6)) != {0.7, 0.8, 0.9}:
        raise RuntimeError("Geometry summary candidate set is invalid")

    max_contained = int(summary["fully_contained_count"].max())
    priority1 = sorted(
        float(x) for x in summary.loc[summary["fully_contained_count"] == max_contained, "candidate_roi_width_fraction"]
    )

    return {
        "lock": lock,
        "summary": summary,
        "candidate_fractions": candidates,
        "aspect_ratio": float(lock["aspect_ratio"]),
        "height_cap_fraction": float(lock["height_cap_fraction"]),
        "priority1_max_contained": max_contained,
        "priority1_candidates": priority1,
        "hashes": {name: sha256_file(geometry_dir / name) for name in required},
    }


class CalibrationSource:
    """Read one calibration dataset from either its directory or a ZIP archive."""

    def __init__(self, source: Path, device: str):
        self.source = source
        self.device = device
        self.source_type = "directory" if source.is_dir() else "zip"
        self.z: zipfile.ZipFile | None = None
        self.manifest_dir = ""
        self.root_dir: Path | None = None
        self.manifest_name = ""
        self.manifest_sha256 = ""
        self._names_set: set[str] | None = None

        if source.is_dir():
            manifest_path = find_unique_file_suffix(source, "manifest.csv")
            self.root_dir = manifest_path.parent
            self.manifest_name = str(manifest_path.relative_to(source))
            raw = manifest_path.read_bytes()
        elif source.is_file() and zipfile.is_zipfile(source):
            self.z = zipfile.ZipFile(source, "r")
            names = self.z.namelist()
            manifest_name = find_unique_suffix(names, "manifest.csv")
            self.manifest_name = manifest_name
            self.manifest_dir = str(Path(manifest_name).parent).replace("\\", "/")
            self._names_set = set(names)
            raw = self.z.read(manifest_name)
        else:
            raise RuntimeError(f"{device}: source must be a directory or ZIP: {source}")

        self.manifest_sha256 = sha256_bytes(raw)
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        needed = [
            "sample_id", "experiment_group", "class_label", "distance_cm", "repeat_index",
            "oriented_width", "oriented_height", "relative_rgb_path", "rgb_sha256"
        ]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise RuntimeError(f"{device}: manifest missing columns {missing}")
        roi = df[df["experiment_group"].str.lower().eq("roi")].copy()
        if len(roi) != 120:
            raise RuntimeError(f"{device}: expected 120 ROI samples, found {len(roi)}")
        if set(roi["class_label"]) != set(LABELS_EXPECTED):
            raise RuntimeError(f"{device}: ROI class set differs from expected labels")
        counts = roi.groupby(["class_label", "distance_cm"]).size()
        if len(counts) != 24 or not (counts == 5).all():
            raise RuntimeError(f"{device}: expected 5 repetitions for each 8-class x 3-distance ROI condition")
        if roi["sample_id"].duplicated().any():
            raise RuntimeError(f"{device}: duplicate sample_id in ROI manifest")
        self.manifest = roi.reset_index(drop=True)

        # Existence gate even in --validate-only mode.
        missing_rgb = [row["relative_rgb_path"] for _, row in self.manifest.iterrows() if not self.exists(row["relative_rgb_path"])]
        if missing_rgb:
            raise RuntimeError(f"{device}: missing {len(missing_rgb)} ROI RGB files; first={missing_rgb[0]}")

    def _zip_member(self, relative_path: str) -> str:
        rel = relative_path.replace("\\", "/").lstrip("/")
        if self.manifest_dir in ("", "."):
            return rel
        return f"{self.manifest_dir.rstrip('/')}/{rel}"

    def exists(self, relative_path: str) -> bool:
        if self.source_type == "directory":
            assert self.root_dir is not None
            return (self.root_dir / relative_path).is_file()
        assert self._names_set is not None
        return self._zip_member(relative_path) in self._names_set

    def read_bytes(self, relative_path: str) -> bytes:
        if self.source_type == "directory":
            assert self.root_dir is not None
            path = self.root_dir / relative_path
            if not path.is_file():
                raise RuntimeError(f"{self.device}: missing RGB file: {path}")
            return path.read_bytes()
        assert self.z is not None
        member = self._zip_member(relative_path)
        try:
            return self.z.read(member)
        except KeyError:
            raise RuntimeError(f"{self.device}: missing RGB file in ZIP: {member}") from None

    def identity(self) -> dict:
        return {
            "source_type": self.source_type,
            "path": str(self.source.resolve()),
            "manifest_path": self.manifest_name,
            "manifest_sha256": self.manifest_sha256,
            "roi_samples": int(len(self.manifest)),
        }

    def close(self):
        if self.z is not None:
            self.z.close()
            self.z = None


def kotlin_round_positive(x: float) -> int:
    # ROI coordinates are non-negative. Kotlin Float.roundToInt follows nearest integer;
    # using floor(x+0.5) matches the positive-coordinate behavior needed here.
    return int(math.floor(float(x) + 0.5))


def roi_int_rect(width: int, height: int, fraction: float, aspect: float, height_cap: float) -> tuple[int, int, int, int, float, float]:
    # Use float32 arithmetic to mirror Android Float config/geometry as closely as possible.
    W = np.float32(width)
    H = np.float32(height)
    f = np.float32(fraction)
    a = np.float32(aspect)
    cap = np.float32(height_cap)
    roi_w = np.minimum(W * f, H * cap * a).astype(np.float32)
    roi_h = (roi_w / a).astype(np.float32)
    left_f = ((W - roi_w) / np.float32(2.0)).astype(np.float32)
    top_f = ((H - roi_h) / np.float32(2.0)).astype(np.float32)
    right_f = ((W + roi_w) / np.float32(2.0)).astype(np.float32)
    bottom_f = ((H + roi_h) / np.float32(2.0)).astype(np.float32)

    left = max(0, min(width - 1, kotlin_round_positive(float(left_f))))
    top = max(0, min(height - 1, kotlin_round_positive(float(top_f))))
    right = max(left + 1, min(width, kotlin_round_positive(float(right_f))))
    bottom = max(top + 1, min(height, kotlin_round_positive(float(bottom_f))))
    return left, top, right, bottom, float(roi_w), float(roi_h)


def resize_bilinear_android(rgb_crop: np.ndarray, out_h: int = 224, out_w: int = 224) -> np.ndarray:
    """Mirror FramePreprocessor.resizeBilinear half-pixel centers, clamped edges."""
    src = np.asarray(rgb_crop, dtype=np.float32)
    h, w, c = src.shape
    if c != 3 or h < 1 or w < 1:
        raise ValueError(f"Invalid crop shape {src.shape}")

    oy = np.arange(out_h, dtype=np.float32)
    ox = np.arange(out_w, dtype=np.float32)
    sy = ((oy + np.float32(0.5)) * np.float32(h) / np.float32(out_h) - np.float32(0.5))
    sx = ((ox + np.float32(0.5)) * np.float32(w) / np.float32(out_w) - np.float32(0.5))
    sy = np.clip(sy, np.float32(0), np.float32(h - 1))
    sx = np.clip(sx, np.float32(0), np.float32(w - 1))
    y0 = np.floor(sy).astype(np.int32)
    x0 = np.floor(sx).astype(np.int32)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    fy = (sy - y0.astype(np.float32))[:, None, None]
    fx = (sx - x0.astype(np.float32))[None, :, None]

    a = src[y0[:, None], x0[None, :], :]
    b = src[y0[:, None], x1[None, :], :]
    d = src[y1[:, None], x0[None, :], :]
    e = src[y1[:, None], x1[None, :], :]
    upper = a + (b - a) * fx
    lower = d + (e - d) * fx
    out = upper + (lower - upper) * fy
    return np.asarray(out, dtype=np.float32)


def get_interpreter(model_content: bytes, num_threads: int):
    errors = []
    try:
        import tensorflow as tf  # type: ignore
        return tf.lite.Interpreter(model_content=model_content, num_threads=num_threads), f"tensorflow {getattr(tf, '__version__', 'unknown')}"
    except Exception as e:
        errors.append(f"tensorflow: {e}")
    try:
        from tflite_runtime.interpreter import Interpreter  # type: ignore
        return Interpreter(model_content=model_content, num_threads=num_threads), "tflite_runtime"
    except Exception as e:
        errors.append(f"tflite_runtime: {e}")
    raise RuntimeError("No TFLite Python interpreter available. Install TensorFlow in the active environment. " + " | ".join(errors))


def validate_interpreter(interpreter, contract: dict):
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()
    out = interpreter.get_output_details()
    if len(inp) != 1 or len(out) != 1:
        raise RuntimeError("Model must have exactly one input and one output")
    if list(map(int, inp[0]["shape"])) != contract["input_shape"]:
        raise RuntimeError(f"Runtime input shape mismatch: {inp[0]['shape']}")
    if list(map(int, out[0]["shape"])) != contract["output_shape"]:
        raise RuntimeError(f"Runtime output shape mismatch: {out[0]['shape']}")
    if np.dtype(inp[0]["dtype"]) != np.dtype(np.float32) or np.dtype(out[0]["dtype"]) != np.dtype(np.float32):
        raise RuntimeError("Runtime tensor dtype is not float32")
    return inp[0], out[0]


def confusion(y_true: list[int], y_pred: list[int], n: int) -> np.ndarray:
    cm = np.zeros((n, n), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        cm[t, p] += 1
    return cm


def metrics_from_cm(cm: np.ndarray, labels: list[str]) -> tuple[dict, pd.DataFrame]:
    total = int(cm.sum())
    accuracy = float(np.trace(cm) / total) if total else 0.0
    rows = []
    for i, label in enumerate(labels):
        tp = int(cm[i, i])
        fn = int(cm[i, :].sum() - tp)
        fp = int(cm[:, i].sum() - tp)
        support = int(cm[i, :].sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        rows.append({"class_label": label, "precision": precision, "recall": recall, "f1": f1, "support": support})
    per_class = pd.DataFrame(rows)
    summary = {
        "accuracy": accuracy,
        "macro_precision": float(per_class["precision"].mean()),
        "macro_recall": float(per_class["recall"].mean()),
        "macro_f1": float(per_class["f1"].mean()),
        "min_recall": float(per_class["recall"].min()),
        "n": total,
    }
    return summary, per_class


def save_confusion_png(cm: np.ndarray, labels: list[str], title: str, out_path: Path):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    im = ax.imshow(cm)
    ax.set_xticks(range(len(labels)), labels=labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels=labels)
    ax.set_xlabel("Prediksi")
    ax.set_ylabel("Ground truth")
    ax.set_title(title)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(int(cm[i, j])), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def run(args):
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_android_bundle(args.android_source)
    geometry = read_geometry(args.geometry_dir)
    poco_source = CalibrationSource(args.poco_source, "poco")
    redmi_source = CalibrationSource(args.redmi_source, "redmi")

    # The app config is still development-only. It must not govern this analysis.
    app_cfg = bundle["app_config"]
    if app_cfg.get("status") not in {"development_uncalibrated", "calibrated"}:
        raise RuntimeError(f"Unexpected app_config status: {app_cfg.get('status')}")
    if abs(float(app_cfg.get("roi_aspect_ratio")) - geometry["aspect_ratio"]) > 1e-9:
        raise RuntimeError("App roi_aspect_ratio differs from geometry lock")

    input_identity = {
        "poco_source": poco_source.identity(),
        "redmi_source": redmi_source.identity(),
        "android_source": {
            "source_type": bundle["source_type"],
            "path": bundle["source_path"],
            "selected_artifact_sha256": bundle["source_hashes"],
        },
        "model_sha256": bundle["model_sha256"],
        "selected_candidate": bundle["identity"]["candidate"],
        "class_names": bundle["labels"],
        "geometry_hashes": geometry["hashes"],
        "geometry_priority1_candidates": geometry["priority1_candidates"],
        "android_source_hashes": bundle["source_hashes"],
        "app_config_status": app_cfg.get("status"),
        "app_config_revision": app_cfg.get("revision"),
        "method_boundary": "ROI model evaluation only; quality gate, CLAHE, confidence threshold, and temporal smoothing disabled",
        "offline_frame_source": "lossless frame_rgb.png from calibration collector after orientation normalization",
        "preprocess": {
            "roi_formula": geometry["lock"]["geometry_formula"],
            "aspect_ratio": geometry["aspect_ratio"],
            "height_cap_fraction": geometry["height_cap_fraction"],
            "resize": "224x224 bilinear, half-pixel centers, clamped edges, no antialias",
            "color_order": "RGB",
            "dtype": "float32",
            "external_value_range": "0..255",
            "normalization": "none outside model",
            "prediction": "argmax of 8 model scores; no confidence threshold",
        },
    }
    (out_dir / "input_identity.json").write_text(json.dumps(input_identity, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.validate_only:
        print(json.dumps(input_identity, indent=2, ensure_ascii=False))
        print("VALIDATION_STATUS=READY_FOR_INFERENCE")
        poco_source.close()
        redmi_source.close()
        return

    threads = int(bundle["selection_lock"].get("runtime", {}).get("threads", 4))
    interpreter, runtime_name = get_interpreter(bundle["raw"]["model.tflite"], threads)
    input_detail, output_detail = validate_interpreter(interpreter, bundle["contract"])

    all_rows = []
    class_to_idx = {c: i for i, c in enumerate(bundle["labels"])}
    try:
        for device, source in [("poco", poco_source), ("redmi", redmi_source)]:
            manifest = source.manifest
            for _, row in manifest.iterrows():
                png_bytes = source.read_bytes(row["relative_rgb_path"])
                actual_img_sha = sha256_bytes(png_bytes)
                if actual_img_sha != row["rgb_sha256"]:
                    raise RuntimeError(f"{device}/{row['sample_id']}: RGB SHA mismatch")
                with Image.open(io.BytesIO(png_bytes)) as im:
                    rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
                height, width = rgb.shape[:2]
                if int(row["oriented_width"]) != width or int(row["oriented_height"]) != height:
                    raise RuntimeError(f"{device}/{row['sample_id']}: manifest dimension mismatch")
                true_label = str(row["class_label"])
                if true_label not in class_to_idx:
                    raise RuntimeError(f"Unexpected class {true_label}")
                for fraction in geometry["candidate_fractions"]:
                    left, top, right, bottom, eff_w_float, eff_h_float = roi_int_rect(
                        width, height, fraction, geometry["aspect_ratio"], geometry["height_cap_fraction"]
                    )
                    crop = rgb[top:bottom, left:right, :]
                    tensor = resize_bilinear_android(crop)
                    batch = tensor[np.newaxis, ...].astype(np.float32, copy=False)
                    interpreter.set_tensor(input_detail["index"], batch)
                    interpreter.invoke()
                    scores = np.asarray(interpreter.get_tensor(output_detail["index"])[0], dtype=np.float32)
                    if scores.shape != (8,) or not np.isfinite(scores).all():
                        raise RuntimeError(f"Invalid model output for {device}/{row['sample_id']} r={fraction}")
                    if not (-0.001 <= float(scores.min()) and float(scores.max()) <= 1.001 and abs(float(scores.sum()) - 1.0) < 0.01):
                        raise RuntimeError(f"Model scores are not valid softmax-like outputs for {device}/{row['sample_id']}")
                    pred_idx = int(np.argmax(scores))
                    pred_label = bundle["labels"][pred_idx]
                    out_row = {
                        "device": device,
                        "sample_id": row["sample_id"],
                        "true_class": true_label,
                        "distance_cm": int(float(row["distance_cm"])),
                        "repeat_index": int(float(row["repeat_index"])),
                        "candidate_roi_width_fraction": fraction,
                        "frame_width": width,
                        "frame_height": height,
                        "roi_left": left,
                        "roi_top": top,
                        "roi_right": right,
                        "roi_bottom": bottom,
                        "roi_width": right - left,
                        "roi_height": bottom - top,
                        "effective_roi_width_fraction": (right - left) / width,
                        "crop_sha256": sha256_bytes(np.ascontiguousarray(crop).tobytes()),
                        "tensor_sha256": sha256_bytes(np.ascontiguousarray(batch).tobytes()),
                        "predicted_class": pred_label,
                        "correct": pred_label == true_label,
                        "top1_score": float(scores[pred_idx]),
                    }
                    for label, score in zip(bundle["labels"], scores):
                        out_row[f"score_{label}"] = float(score)
                    all_rows.append(out_row)
    finally:
        poco_source.close()
        redmi_source.close()

    pred = pd.DataFrame(all_rows)
    if len(pred) != 720:
        raise RuntimeError(f"Expected 720 candidate predictions, found {len(pred)}")
    if pred.duplicated(["device", "sample_id", "candidate_roi_width_fraction"]).any():
        raise RuntimeError("Duplicate prediction key")
    pred.to_csv(out_dir / "roi_model_predictions.csv", index=False)

    summary_rows = []
    per_class_parts = []
    for fraction in geometry["candidate_fractions"]:
        sub = pred[pred["candidate_roi_width_fraction"] == fraction].copy()
        y_true = [class_to_idx[x] for x in sub["true_class"]]
        y_pred = [class_to_idx[x] for x in sub["predicted_class"]]
        cm = confusion(y_true, y_pred, len(bundle["labels"]))
        metrics, pc = metrics_from_cm(cm, bundle["labels"])
        summary_rows.append({"candidate_roi_width_fraction": fraction, **metrics})
        pc.insert(0, "candidate_roi_width_fraction", fraction)
        per_class_parts.append(pc)
        pd.DataFrame(cm, index=bundle["labels"], columns=bundle["labels"]).to_csv(
            out_dir / f"confusion_matrix_{int(round(fraction*100)):02d}.csv"
        )
        save_confusion_png(
            cm, bundle["labels"], f"Confusion Matrix ROI r={fraction:.2f}",
            out_dir / f"confusion_matrix_{int(round(fraction*100)):02d}.png"
        )

    summary = pd.DataFrame(summary_rows).sort_values("candidate_roi_width_fraction")
    summary.to_csv(out_dir / "roi_model_summary.csv", index=False)
    pd.concat(per_class_parts, ignore_index=True).to_csv(out_dir / "roi_model_per_class.csv", index=False)

    # Diagnostics by device and distance, still using the fixed 8-class label universe.
    diag_rows = []
    for fraction in geometry["candidate_fractions"]:
        for device, sub in pred[pred["candidate_roi_width_fraction"] == fraction].groupby("device"):
            cm = confusion([class_to_idx[x] for x in sub["true_class"]], [class_to_idx[x] for x in sub["predicted_class"]], 8)
            m, _ = metrics_from_cm(cm, bundle["labels"])
            diag_rows.append({"scope": "device", "scope_value": device, "candidate_roi_width_fraction": fraction, **m})
        for distance, sub in pred[pred["candidate_roi_width_fraction"] == fraction].groupby("distance_cm"):
            cm = confusion([class_to_idx[x] for x in sub["true_class"]], [class_to_idx[x] for x in sub["predicted_class"]], 8)
            m, _ = metrics_from_cm(cm, bundle["labels"])
            diag_rows.append({"scope": "distance_cm", "scope_value": int(distance), "candidate_roi_width_fraction": fraction, **m})
    pd.DataFrame(diag_rows).to_csv(out_dir / "roi_model_diagnostics.csv", index=False)

    # Tensor equivalence helps explain cases where the height cap makes two requested fractions identical.
    eq_rows = []
    for device in sorted(pred["device"].unique()):
        d = pred[pred["device"] == device]
        piv = d.pivot(index="sample_id", columns="candidate_roi_width_fraction", values="tensor_sha256")
        for a, b in [(0.7, 0.8), (0.7, 0.9), (0.8, 0.9)]:
            if a in piv.columns and b in piv.columns:
                same = int((piv[a] == piv[b]).sum())
                eq_rows.append({"device": device, "candidate_a": a, "candidate_b": b, "identical_tensor_count": same, "total": int(len(piv)), "identical_rate": same / len(piv)})
    pd.DataFrame(eq_rows).to_csv(out_dir / "roi_tensor_equivalence.csv", index=False)

    # Lexicographic thesis decision: containment -> macro F1 -> excessive background.
    geo = geometry["summary"].copy()
    merged = geo.merge(summary, on="candidate_roi_width_fraction", how="left", validate="one_to_one")
    max_cont = merged["fully_contained_count"].max()
    p1 = merged[merged["fully_contained_count"] == max_cont].copy()
    decision_trace = [{
        "priority": 1,
        "criterion": "fully_contained_count_max",
        "candidates_before": [float(x) for x in merged["candidate_roi_width_fraction"]],
        "best_value": int(max_cont),
        "candidates_after": [float(x) for x in p1["candidate_roi_width_fraction"]],
    }]
    current = p1
    if len(current) > 1:
        best_f1 = current["macro_f1"].max()
        current = current[np.isclose(current["macro_f1"], best_f1, rtol=0, atol=1e-12)].copy()
        decision_trace.append({
            "priority": 2,
            "criterion": "macro_f1_max",
            "best_value": float(best_f1),
            "candidates_after": [float(x) for x in current["candidate_roi_width_fraction"]],
        })
    if len(current) > 1:
        best_bg = current["excessive_background_count"].min()
        current = current[current["excessive_background_count"] == best_bg].copy()
        decision_trace.append({
            "priority": 3,
            "criterion": "excessive_background_count_min",
            "best_value": int(best_bg),
            "candidates_after": [float(x) for x in current["candidate_roi_width_fraction"]],
        })
    if len(current) != 1:
        raise RuntimeError(f"ROI selection remains tied after all thesis criteria: {current['candidate_roi_width_fraction'].tolist()}")
    selected = float(current.iloc[0]["candidate_roi_width_fraction"])

    selection = {
        "status": "roi_selected",
        "selected_roi_width_fraction": selected,
        "selection_order": ["fully_contained_count", "macro_f1", "excessive_background_count"],
        "decision_trace": decision_trace,
        "important_rule": "Lower-priority criteria never override a unique winner at a higher-priority criterion.",
        "model_runtime": runtime_name,
        "model_sha256": bundle["model_sha256"],
        "input_identity_sha256": sha256_bytes((out_dir / "input_identity.json").read_bytes()),
        "predictions_sha256": sha256_file(out_dir / "roi_model_predictions.csv"),
        "summary_sha256": sha256_file(out_dir / "roi_model_summary.csv"),
        "geometry_summary_sha256": geometry["hashes"]["roi_geometric_summary.csv"],
    }
    (out_dir / "roi_selection_decision.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False), encoding="utf-8")

    output_hashes = {}
    for p in sorted(out_dir.iterdir()):
        if p.is_file() and p.name != "roi_model_evaluation_lock.json":
            output_hashes[p.name] = sha256_file(p)
    final_lock = {
        "status": "roi_model_evaluation_complete",
        "rows": int(len(pred)),
        "samples_per_candidate": 240,
        "candidate_fractions": geometry["candidate_fractions"],
        "selected_roi_width_fraction": selected,
        "model_sha256": bundle["model_sha256"],
        "input_sources": {
            "poco": poco_source.identity(),
            "redmi": redmi_source.identity(),
            "android": {
                "source_type": bundle["source_type"],
                "path": bundle["source_path"],
                "selected_artifact_sha256": bundle["source_hashes"],
            },
        },
        "geometry_lock_sha256": sha256_file(args.geometry_dir / "roi_geometry_lock.json"),
        "output_sha256": output_hashes,
    }
    (out_dir / "roi_model_evaluation_lock.json").write_text(json.dumps(final_lock, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== ROI MODEL SUMMARY ===")
    print(summary.to_string(index=False))
    print("\n=== ROI SELECTION ===")
    print(json.dumps(selection, indent=2, ensure_ascii=False))
    print(f"\nOutput: {out_dir}")
    print("ROI_MODEL_EVALUATION_STATUS=COMPLETE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--poco", "--poco-source", "--poco-zip",
        dest="poco_source", required=True, type=Path,
        help="POCO calibration directory or ZIP"
    )
    ap.add_argument(
        "--redmi", "--redmi-source", "--redmi-zip",
        dest="redmi_source", required=True, type=Path,
        help="Redmi calibration directory or ZIP"
    )
    ap.add_argument(
        "--android", "--android-source", "--android-zip",
        dest="android_source", required=True, type=Path,
        help="Android project directory or ZIP"
    )
    ap.add_argument("--geometry-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--validate-only", action="store_true", help="Validate all locked inputs but do not load/run TFLite")
    args = ap.parse_args()

    for name, p in [
        ("POCO", args.poco_source),
        ("Redmi", args.redmi_source),
        ("Android", args.android_source),
    ]:
        if not p.exists():
            raise FileNotFoundError(f"{name} source not found: {p}")
        if not (p.is_dir() or (p.is_file() and zipfile.is_zipfile(p))):
            raise RuntimeError(f"{name} source must be a directory or ZIP: {p}")

    if not args.geometry_dir.is_dir():
        raise NotADirectoryError(args.geometry_dir)

    # Keep Stage-4 outputs separate from the locked geometry input directory.
    # The output may be a child directory of geometry-dir, but should not be exactly the same directory.
    if args.out.resolve() == args.geometry_dir.resolve():
        raise RuntimeError(
            "--out must not be exactly the same directory as --geometry-dir. "
            "Use a child folder such as hasil_roi_annotation/04_roi_model_evaluation."
        )

    run(args)


if __name__ == "__main__":
    main()
