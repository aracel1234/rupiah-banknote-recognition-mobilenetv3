#!/usr/bin/env python3
"""Stage 7 - CLAHE calibration/evaluation for thesis section 5.7.2.

Methodological boundary
-----------------------
- Uses the locked ROI from Stage 4 and locked lighting thresholds from Stage 6.
- CLAHE selection is evaluated on the 160 physically labelled `redup` quality
  samples (8 classes x 2 focus conditions x 5 repetitions x 2 devices).
- Configurations: no CLAHE plus clip limit {1.5,2.0,2.5} x grid {4,8}.
- The CLAHE algorithm mirrors the custom Android LuminanceClahe.kt semantics.
- CLAHE is applied to native camera Y after limited-range expansion, then mapped
  back to native Y, matching current QualityGate.kt.
- Stored calibration evidence contains RGB and Y but not raw U/V planes.
  For offline replay, enhanced RGB preserves the chroma residual of the stored
  RGB by adding the limited-BT.601 luminance delta equally to R/G/B. This is
  exact up to the stored RGB quantization for non-clipped source channels; the
  script records source clipping fractions. If a CLAHE configuration is selected,
  Android parity confirmation is required before final operational lock.
- Model inference uses the locked Dynamic Range TFLite model and the same
  half-pixel bilinear 224x224 resize used in FramePreprocessor.kt.
- A CLAHE configuration is eligible only if the paired stratified bootstrap 95%
  CI of delta macro-F1 versus no CLAHE is strictly above zero AND no class has
  zero recall.
- Bootstrap: 2,000 iterations by default, seed 42, paired resampling within
  (class_label, device, focus_condition) strata.
- If multiple eligible configurations tie on observed macro-F1, no hidden
  tie-break is applied.

Compatible with Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
from PIL import Image

LABELS = ["1000", "2000", "5000", "10000", "20000", "50000", "100000", "nonuang"]
CONFIGS = [
    ("none", None, None),
    ("clahe_c1p5_g4", 1.5, 4),
    ("clahe_c1p5_g8", 1.5, 8),
    ("clahe_c2p0_g4", 2.0, 4),
    ("clahe_c2p0_g8", 2.0, 8),
    ("clahe_c2p5_g4", 2.5, 4),
    ("clahe_c2p5_g8", 2.5, 8),
]
EPS = 1e-12


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_unique_suffix(names, suffix: str) -> str:
    hits = [n for n in names if n.replace("\\", "/").endswith(suffix)]
    if len(hits) != 1:
        raise RuntimeError("Expected exactly one '*%s', found %d: %r" % (suffix, len(hits), hits[:5]))
    return hits[0]


def find_unique_file_suffix(root: Path, suffix: str) -> Path:
    hits = [p for p in root.rglob("*") if p.is_file() and p.as_posix().endswith(suffix)]
    if len(hits) != 1:
        raise RuntimeError("Expected exactly one '*%s' under %s, found %d" % (suffix, root, len(hits)))
    return hits[0]


class CalibrationSource:
    def __init__(self, source: Path, device: str):
        self.source = source
        self.device = device
        self.source_type = "directory" if source.is_dir() else "zip"
        self.z = None
        self.root_dir = None
        self.manifest_dir = ""
        self.manifest_name = ""
        self._names = None

        if source.is_dir():
            manifest_path = find_unique_file_suffix(source, "manifest.csv")
            self.root_dir = manifest_path.parent
            self.manifest_name = str(manifest_path.relative_to(source))
            raw = manifest_path.read_bytes()
        elif source.is_file() and zipfile.is_zipfile(source):
            self.z = zipfile.ZipFile(source, "r")
            names = self.z.namelist()
            self._names = set(names)
            self.manifest_name = find_unique_suffix(names, "manifest.csv")
            self.manifest_dir = str(Path(self.manifest_name).parent).replace("\\", "/")
            raw = self.z.read(self.manifest_name)
        else:
            raise RuntimeError("%s source must be directory or ZIP: %s" % (device, source))

        self.manifest_sha256 = sha256_bytes(raw)
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        needed = [
            "sample_id", "experiment_group", "class_label", "lighting", "focus_condition",
            "repeat_index", "oriented_width", "oriented_height", "relative_rgb_path",
            "relative_luma_path", "rgb_sha256", "luma_sha256"
        ]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise RuntimeError("%s manifest missing columns: %s" % (device, missing))
        q = df[df["experiment_group"].str.lower().eq("quality")].copy()
        if len(q) != 240:
            raise RuntimeError("%s expected 240 quality samples, got %d" % (device, len(q)))
        if set(q["class_label"].astype(str)) != set(LABELS):
            raise RuntimeError("%s quality class set mismatch" % device)
        if q["sample_id"].duplicated().any():
            raise RuntimeError("%s duplicate quality sample_id" % device)
        self.manifest = q.set_index("sample_id", drop=False)

    def _member(self, relative: str) -> str:
        rel = str(relative).replace("\\", "/").lstrip("/")
        if self.manifest_dir in ("", "."):
            return rel
        return self.manifest_dir.rstrip("/") + "/" + rel

    def read_bytes(self, relative: str) -> bytes:
        if self.source_type == "directory":
            p = self.root_dir / relative
            if not p.is_file():
                raise RuntimeError("Missing file: %s" % p)
            return p.read_bytes()
        member = self._member(relative)
        try:
            return self.z.read(member)
        except KeyError:
            raise RuntimeError("Missing ZIP member: %s" % member) from None

    def row(self, sample_id: str) -> pd.Series:
        if sample_id not in self.manifest.index:
            raise RuntimeError("%s sample not found in manifest: %s" % (self.device, sample_id))
        return self.manifest.loc[sample_id]

    def identity(self) -> dict:
        return {
            "device": self.device,
            "source_type": self.source_type,
            "path": str(self.source.resolve()),
            "manifest_path": self.manifest_name,
            "manifest_sha256": self.manifest_sha256,
            "quality_samples": int(len(self.manifest)),
        }

    def close(self):
        if self.z is not None:
            self.z.close()
            self.z = None


def load_android(android_source: Path) -> dict:
    wanted = {
        "model.tflite": "app/src/main/assets/model/model.tflite",
        "class_names.json": "app/src/main/assets/model/class_names.json",
        "tensor_contract.json": "app/src/main/assets/model/tensor_contract.json",
        "model_identity.json": "app/src/main/assets/model/model_identity.json",
        "selection_lock.json": "app/src/main/assets/model/selection_lock.json",
        "asset_integrity.json": "app/src/main/assets/model/asset_integrity.json",
        "app_config.json": "app/src/main/assets/app_config.json",
        "LuminanceClahe.kt": "app/src/main/java/id/ac/ub/rupiah/image/LuminanceClahe.kt",
        "QualityGate.kt": "app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt",
        "FramePreprocessor.kt": "app/src/main/java/id/ac/ub/rupiah/image/FramePreprocessor.kt",
    }
    data = {}
    paths = {}
    source_type = "directory" if android_source.is_dir() else "zip"
    if android_source.is_dir():
        for key, suffix in wanted.items():
            p = find_unique_file_suffix(android_source, suffix)
            paths[key] = str(p.relative_to(android_source))
            data[key] = p.read_bytes()
    elif android_source.is_file() and zipfile.is_zipfile(android_source):
        with zipfile.ZipFile(android_source, "r") as z:
            names = z.namelist()
            for key, suffix in wanted.items():
                n = find_unique_suffix(names, suffix)
                paths[key] = n
                data[key] = z.read(n)
    else:
        raise RuntimeError("Android source must be directory or ZIP: %s" % android_source)

    integrity = json.loads(data["asset_integrity.json"])
    for name in ["model.tflite", "class_names.json", "tensor_contract.json", "model_identity.json", "selection_lock.json"]:
        actual = sha256_bytes(data[name])
        if integrity.get(name) != actual:
            raise RuntimeError("Android model asset hash mismatch: %s" % name)

    labels = json.loads(data["class_names.json"])
    contract = json.loads(data["tensor_contract.json"])
    identity = json.loads(data["model_identity.json"])
    selection = json.loads(data["selection_lock.json"])
    app_cfg = json.loads(data["app_config.json"])
    model_sha = sha256_bytes(data["model.tflite"])

    if labels != LABELS or contract.get("class_names") != LABELS:
        raise RuntimeError("Unexpected model class order")
    if contract.get("input_shape") != [1, 224, 224, 3] or contract.get("output_shape") != [1, 8]:
        raise RuntimeError("Unexpected model tensor shape")
    if contract.get("input_dtype") != "float32" or contract.get("output_dtype") != "float32":
        raise RuntimeError("Expected float32 model interface")
    if identity.get("candidate") != "dynamic_range" or selection.get("selected_candidate") != "dynamic_range":
        raise RuntimeError("Expected locked Dynamic Range candidate")
    for value in [identity.get("sha256"), contract.get("model_sha256"), selection.get("model_sha256")]:
        if value != model_sha:
            raise RuntimeError("Model identity mismatch")
    if app_cfg.get("yuv_range") != "limited_bt601":
        raise RuntimeError("Stage 7 currently requires yuv_range=limited_bt601")

    # Source semantics gates: do not silently use a different Android implementation.
    clahe_src = data["LuminanceClahe.kt"].decode("utf-8", errors="replace")
    gate_src = data["QualityGate.kt"].decode("utf-8", errors="replace")
    prep_src = data["FramePreprocessor.kt"].decode("utf-8", errors="replace")
    required_clahe_tokens = ["clipLimit *", "area /", "256", "cumulative", "255f", "floor(tx)", "floor(ty)"]
    if not all(tok in clahe_src for tok in required_clahe_tokens):
        raise RuntimeError("LuminanceClahe.kt semantics no longer match Stage 7 port assumptions")
    if "originalMean < config.lumaMin" not in gate_src or "clahe.apply" not in gate_src:
        raise RuntimeError("QualityGate.kt CLAHE trigger semantics changed")
    if "1.16438356f" not in prep_src:
        raise RuntimeError("FramePreprocessor.kt limited BT.601 luminance coefficient changed")

    return {
        "raw": data,
        "paths": paths,
        "labels": labels,
        "contract": contract,
        "app_config": app_cfg,
        "model_sha256": model_sha,
        "source_type": source_type,
        "source_path": str(android_source.resolve()),
        "source_hashes": {
            "model.tflite": model_sha,
            "LuminanceClahe.kt": sha256_bytes(data["LuminanceClahe.kt"]),
            "QualityGate.kt": sha256_bytes(data["QualityGate.kt"]),
            "FramePreprocessor.kt": sha256_bytes(data["FramePreprocessor.kt"]),
            "app_config.json": sha256_bytes(data["app_config.json"]),
        },
    }


def load_stage6(lighting_dir: Path) -> dict:
    required = [
        "lighting_calibration_evidence_lock.json",
        "lighting_threshold_evidence.json",
        "lighting_sample_predictions.csv",
        "lighting_confusion_matrix.csv",
        "lighting_diagnostics.csv",
        "input_identity.json",
    ]
    for name in required:
        if not (lighting_dir / name).is_file():
            raise FileNotFoundError("Missing Stage 6 artifact: %s" % (lighting_dir / name))

    lock_path = lighting_dir / "lighting_calibration_evidence_lock.json"
    ev_path = lighting_dir / "lighting_threshold_evidence.json"
    pred_path = lighting_dir / "lighting_sample_predictions.csv"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    if lock.get("status") != "lighting_calibration_evidence_locked":
        raise RuntimeError("Stage 6 lock status invalid")
    if ev.get("selection_status") != "selected_unique_macro_f1_maximum":
        raise RuntimeError("Stage 6 lighting thresholds are not uniquely selected")
    for name, expected in lock.get("output_sha256", {}).items():
        p = lighting_dir / name
        if not p.is_file() or sha256_file(p) != expected:
            raise RuntimeError("Stage 6 output hash mismatch: %s" % name)

    df = pd.read_csv(pred_path, dtype={"class_label": str})
    if len(df) != 480 or df.duplicated(["device", "sample_id"]).any():
        raise RuntimeError("Stage 6 sample table must contain 480 unique device/sample rows")
    if df["lighting"].value_counts().to_dict() != {"normal": 160, "redup": 160, "terang": 160}:
        raise RuntimeError("Stage 6 lighting counts are not balanced 160/160/160")
    low = float(ev["selected_luma_min"])
    high = float(ev["selected_luma_max"])
    if not low < high:
        raise RuntimeError("Invalid selected lighting threshold order")

    y = df["roi_mean_y_raw"].to_numpy(float)
    recomputed = np.where(y < low, "redup", np.where(y > high, "terang", "normal"))
    if not np.array_equal(recomputed, df["predicted_lighting"].astype(str).to_numpy()):
        raise RuntimeError("Stage 6 predicted_lighting does not reproduce from selected thresholds")

    dim = df[df["lighting"].astype(str).eq("redup")].copy().reset_index(drop=True)
    if len(dim) != 160:
        raise RuntimeError("Expected 160 physically dim samples")
    if set(dim["class_label"].astype(str)) != set(LABELS):
        raise RuntimeError("Dim sample class set mismatch")
    per_class = dim.groupby("class_label").size()
    if not (per_class == 20).all():
        raise RuntimeError("Expected 20 dim samples per class")

    return {
        "lock": lock,
        "evidence": ev,
        "samples": df,
        "dim": dim,
        "luma_min": low,
        "luma_max": high,
        "lock_sha256": sha256_file(lock_path),
        "evidence_sha256": sha256_file(ev_path),
        "sample_sha256": sha256_file(pred_path),
    }


def decode_rgb(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)


def decode_luma(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert("L"), dtype=np.uint8)


def android_clahe_native_y(y_native: np.ndarray, clip_limit: float, grid: int) -> np.ndarray:
    """Port of current LuminanceClahe.kt + QualityGate limited-range mapping."""
    raw = np.asarray(y_native, dtype=np.float32)
    h, w = raw.shape
    if w < grid or h < grid:
        raise RuntimeError("ROI smaller than CLAHE grid")

    work = np.clip(
        (raw - np.float32(16.0)) * (np.float32(255.0) / np.float32(219.0)),
        np.float32(0.0), np.float32(255.0)
    ).astype(np.float32)

    lut = np.empty((grid, grid, 256), dtype=np.float32)
    for gy in range(grid):
        for gx in range(grid):
            x0 = gx * w // grid
            x1 = (gx + 1) * w // grid
            y0 = gy * h // grid
            y1 = (gy + 1) * h // grid
            area = (x1 - x0) * (y1 - y0)
            vals = np.clip(work[y0:y1, x0:x1].astype(np.int32), 0, 255)
            hist = np.bincount(vals.ravel(), minlength=256).astype(np.int64)
            limit = max(1, int(float(clip_limit) * area / 256.0))
            excess = int(np.maximum(hist - limit, 0).sum())
            hist = np.minimum(hist, limit)
            share = excess // 256
            remainder = excess % 256
            if share:
                hist += share
            if remainder > 0:
                idx = (np.arange(remainder, dtype=np.int64) * 256 // remainder).astype(np.int64)
                # Kotlin loop increments each selected bin once.
                np.add.at(hist, idx, 1)
            cumulative = np.cumsum(hist, dtype=np.int64)
            lut[gy, gx, :] = (cumulative.astype(np.float32) * np.float32(255.0) / np.float32(area))

    cols = np.arange(w, dtype=np.float32)
    rows = np.arange(h, dtype=np.float32)
    tx = (cols + np.float32(0.5)) * np.float32(grid) / np.float32(w) - np.float32(0.5)
    ty = (rows + np.float32(0.5)) * np.float32(grid) / np.float32(h) - np.float32(0.5)
    ix = np.floor(tx).astype(np.int32)
    iy = np.floor(ty).astype(np.int32)
    fx = (tx - ix.astype(np.float32)).astype(np.float32)
    fy = (ty - iy.astype(np.float32)).astype(np.float32)
    x0 = np.clip(ix, 0, grid - 1)
    x1 = np.clip(ix + 1, 0, grid - 1)
    y0 = np.clip(iy, 0, grid - 1)
    y1 = np.clip(iy + 1, 0, grid - 1)
    values = np.clip(work.astype(np.int32), 0, 255)

    Y0 = y0[:, None]
    Y1 = y1[:, None]
    X0 = x0[None, :]
    X1 = x1[None, :]
    FX = fx[None, :]
    FY = fy[:, None]

    a = lut[Y0, X0, values] * (np.float32(1.0) - FX) + lut[Y0, X1, values] * FX
    b = lut[Y1, X0, values] * (np.float32(1.0) - FX) + lut[Y1, X1, values] * FX
    enhanced_full = a * (np.float32(1.0) - FY) + b * FY

    native = np.float32(16.0) + enhanced_full * (np.float32(219.0) / np.float32(255.0))
    return np.asarray(native, dtype=np.float32)


def laplacian_variance4(y: np.ndarray) -> float:
    a = np.asarray(y, dtype=np.float64)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    center = a[1:-1, 1:-1]
    lap = (
        a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4.0 * center
    )
    return float(max(0.0, np.mean(lap * lap) - np.mean(lap) ** 2))


def enhanced_rgb_from_stored(rgb: np.ndarray, y_raw: np.ndarray, y_processed: np.ndarray) -> np.ndarray:
    delta = np.float32(1.16438356) * (np.asarray(y_processed, np.float32) - np.asarray(y_raw, np.float32))
    out = np.asarray(rgb, np.float32) + delta[:, :, None]
    return np.clip(out, np.float32(0.0), np.float32(255.0)).astype(np.float32)


def resize_bilinear_android(rgb_crop: np.ndarray, out_h: int = 224, out_w: int = 224) -> np.ndarray:
    src = np.asarray(rgb_crop, dtype=np.float32)
    h, w, c = src.shape
    if c != 3 or h < 1 or w < 1:
        raise ValueError("Invalid RGB crop shape %r" % (src.shape,))
    oy = np.arange(out_h, dtype=np.float32)
    ox = np.arange(out_w, dtype=np.float32)
    sy = ((oy + np.float32(0.5)) * np.float32(h) / np.float32(out_h) - np.float32(0.5))
    sx = ((ox + np.float32(0.5)) * np.float32(w) / np.float32(out_w) - np.float32(0.5))
    sy = np.clip(sy, 0, h - 1)
    sx = np.clip(sx, 0, w - 1)
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
    return np.asarray(upper + (lower - upper) * fy, dtype=np.float32)


def get_interpreter(model_content: bytes, num_threads: int = 1):
    errors = []
    try:
        import tensorflow as tf  # type: ignore
        return tf.lite.Interpreter(model_content=model_content, num_threads=num_threads), "tensorflow %s" % getattr(tf, "__version__", "unknown")
    except Exception as e:
        errors.append("tensorflow: %s" % e)
    try:
        from tflite_runtime.interpreter import Interpreter  # type: ignore
        return Interpreter(model_content=model_content, num_threads=num_threads), "tflite_runtime"
    except Exception as e:
        errors.append("tflite_runtime: %s" % e)
    raise RuntimeError("No TFLite Python interpreter available. " + " | ".join(errors))


def validate_interpreter(interpreter, contract: dict):
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()
    out = interpreter.get_output_details()
    if len(inp) != 1 or len(out) != 1:
        raise RuntimeError("Model must have exactly one input/output")
    if list(map(int, inp[0]["shape"])) != contract["input_shape"]:
        raise RuntimeError("Runtime input shape mismatch")
    if list(map(int, out[0]["shape"])) != contract["output_shape"]:
        raise RuntimeError("Runtime output shape mismatch")
    if np.dtype(inp[0]["dtype"]) != np.dtype(np.float32) or np.dtype(out[0]["dtype"]) != np.dtype(np.float32):
        raise RuntimeError("Runtime tensors must be float32")
    return inp[0], out[0]


def cm_metrics(true_idx: np.ndarray, pred_idx: np.ndarray):
    cm = np.zeros((len(LABELS), len(LABELS)), dtype=np.int64)
    np.add.at(cm, (true_idx, pred_idx), 1)
    rows = []
    for i, label in enumerate(LABELS):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum() - tp)
        fn = int(cm[i, :].sum() - tp)
        support = int(cm[i, :].sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        rows.append({"class_label": label, "precision": p, "recall": r, "f1": f, "support": support})
    per = pd.DataFrame(rows)
    summary = {
        "n": int(cm.sum()),
        "accuracy": float(np.trace(cm) / cm.sum()) if cm.sum() else 0.0,
        "macro_precision": float(per["precision"].mean()),
        "macro_recall": float(per["recall"].mean()),
        "macro_f1": float(per["f1"].mean()),
        "min_recall": float(per["recall"].min()),
    }
    return cm, summary, per


def macro_f1_only(true_idx: np.ndarray, pred_idx: np.ndarray) -> float:
    return cm_metrics(true_idx, pred_idx)[1]["macro_f1"]


def paired_bootstrap(meta: pd.DataFrame, true_idx: np.ndarray, pred_by_config: dict, iterations: int, seed: int):
    strata = []
    for _, g in meta.groupby(["class_label", "device", "focus_condition"], sort=True):
        strata.append(g.index.to_numpy(dtype=np.int64))
    if len(strata) != 32 or any(len(s) != 5 for s in strata):
        raise RuntimeError("Expected 32 bootstrap strata of 5 samples each")

    rng = np.random.default_rng(seed)
    config_ids = [c[0] for c in CONFIGS if c[0] != "none"]
    deltas = {cid: np.empty(iterations, dtype=np.float64) for cid in config_ids}
    baseline = pred_by_config["none"]

    for b in range(iterations):
        idx = np.concatenate([rng.choice(s, size=len(s), replace=True) for s in strata])
        base_f1 = macro_f1_only(true_idx[idx], baseline[idx])
        for cid in config_ids:
            f1 = macro_f1_only(true_idx[idx], pred_by_config[cid][idx])
            deltas[cid][b] = f1 - base_f1
    return deltas


def validate_inputs(args):
    stage6 = load_stage6(args.lighting_dir)
    android = load_android(args.android)
    sources = {
        "poco": CalibrationSource(args.poco, "poco"),
        "redmi": CalibrationSource(args.redmi, "redmi"),
    }
    dim = stage6["dim"].copy()

    # Verify every physical dim sample against original manifest and stored hashes.
    clipped = []
    for i, row in dim.iterrows():
        dev = str(row["device"])
        sid = str(row["sample_id"])
        src = sources[dev]
        m = src.row(sid)
        if str(m["lighting"]) != "redup" or str(m["class_label"]) != str(row["class_label"]):
            raise RuntimeError("Manifest label mismatch for %s/%s" % (dev, sid))
        rgb_b = src.read_bytes(str(m["relative_rgb_path"]))
        y_b = src.read_bytes(str(m["relative_luma_path"]))
        if sha256_bytes(rgb_b) != str(m["rgb_sha256"]):
            raise RuntimeError("RGB hash mismatch for %s/%s" % (dev, sid))
        if sha256_bytes(y_b) != str(m["luma_sha256"]):
            raise RuntimeError("Luma hash mismatch for %s/%s" % (dev, sid))
        if str(row["luma_png_sha256"]) != str(m["luma_sha256"]):
            raise RuntimeError("Stage 6 luma hash mismatch for %s/%s" % (dev, sid))
        rgb = decode_rgb(rgb_b)
        lum = decode_luma(y_b)
        if rgb.shape[:2] != lum.shape:
            raise RuntimeError("RGB/luma dimension mismatch for %s/%s" % (dev, sid))
        l, t, r, b = [int(row[x]) for x in ["roi_left", "roi_top", "roi_right", "roi_bottom"]]
        if not (0 <= l < r <= rgb.shape[1] and 0 <= t < b <= rgb.shape[0]):
            raise RuntimeError("ROI outside image for %s/%s" % (dev, sid))
        rc = rgb[t:b, l:r]
        clipped.append(float(np.any((rc == 0) | (rc == 255), axis=2).mean()))

    trigger = stage6["samples"][stage6["samples"]["roi_mean_y_raw"] < stage6["luma_min"]]
    validation = {
        "status": "READY_FOR_CLAHE_EVALUATION",
        "selected_roi_width_fraction": float(stage6["evidence"]["selected_roi_width_fraction"]),
        "selected_luma_min": stage6["luma_min"],
        "selected_luma_max": stage6["luma_max"],
        "physical_dim_samples": int(len(dim)),
        "dim_samples_per_class": {str(k): int(v) for k, v in dim.groupby("class_label").size().items()},
        "dim_focus_counts": {str(k): int(v) for k, v in dim["focus_condition"].value_counts().sort_index().items()},
        "dim_device_counts": {str(k): int(v) for k, v in dim["device"].value_counts().sort_index().items()},
        "physical_dim_triggered_by_luma_min": int((dim["roi_mean_y_raw"] < stage6["luma_min"]).sum()),
        "operational_luma_min_trigger_count_all_quality": int(len(trigger)),
        "operational_trigger_true_lighting_counts": {str(k): int(v) for k, v in trigger["lighting"].value_counts().sort_index().items()},
        "mean_source_roi_rgb_clipped_pixel_fraction_dim": float(np.mean(clipped)),
        "max_source_roi_rgb_clipped_pixel_fraction_dim": float(np.max(clipped)),
        "stage6_lock_sha256": stage6["lock_sha256"],
        "stage6_evidence_sha256": stage6["evidence_sha256"],
        "stage6_sample_predictions_sha256": stage6["sample_sha256"],
        "android": {
            "source_type": android["source_type"],
            "path": android["source_path"],
            "model_sha256": android["model_sha256"],
            "source_hashes": android["source_hashes"],
        },
        "sources": [sources["poco"].identity(), sources["redmi"].identity()],
        "configs": [
            {"config_id": cid, "clip_limit": clip, "grid": grid}
            for cid, clip, grid in CONFIGS
        ],
        "bootstrap": {
            "iterations": int(args.bootstrap_iterations),
            "seed": int(args.bootstrap_seed),
            "paired": True,
            "strata": ["class_label", "device", "focus_condition"],
            "ci": "percentile_2.5_97.5",
        },
        "selection_rule": "eligible iff 95% paired bootstrap CI lower bound of delta macro-F1 vs none > 0 and min class recall > 0; among eligible choose highest observed macro-F1; exact ties require explicit resolution; if none eligible select none",
        "reconstruction_method": "stored RGB + limited-BT.601 luminance delta after Android CLAHE; raw U/V were not serialized",
        "requires_android_parity_confirmation_if_clahe_selected": True,
    }
    return stage6, android, sources, validation


def run_full(args, stage6, android, sources, validation):
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    dim = stage6["dim"].copy().reset_index(drop=True)
    label_idx = {x: i for i, x in enumerate(LABELS)}
    true_idx = np.array([label_idx[str(x)] for x in dim["class_label"]], dtype=np.int64)

    interpreter, runtime_name = get_interpreter(android["raw"]["model.tflite"], 1)
    inp, outp = validate_interpreter(interpreter, android["contract"])

    prediction_rows = []
    pred_by_config = {cid: np.empty(len(dim), dtype=np.int64) for cid, _, _ in CONFIGS}

    # Cache source image/ROI data once per sample.
    cached = []
    for i, row in dim.iterrows():
        dev = str(row["device"])
        sid = str(row["sample_id"])
        src = sources[dev]
        m = src.row(sid)
        rgb_b = src.read_bytes(str(m["relative_rgb_path"]))
        y_b = src.read_bytes(str(m["relative_luma_path"]))
        rgb = decode_rgb(rgb_b)
        lum = decode_luma(y_b)
        l, t, r, b = [int(row[x]) for x in ["roi_left", "roi_top", "roi_right", "roi_bottom"]]
        rgb_roi = rgb[t:b, l:r].astype(np.float32)
        y_roi = lum[t:b, l:r].astype(np.float32)
        clipped_fraction = float(np.any((rgb_roi <= 0) | (rgb_roi >= 255), axis=2).mean())
        cached.append((rgb_roi, y_roi, clipped_fraction, m))

    for cid, clip, grid in CONFIGS:
        for i, row in dim.iterrows():
            rgb_roi, y_roi, clipped_fraction, m = cached[i]
            if cid == "none":
                y_processed = y_roi
                rgb_processed = rgb_roi
                applied = False
            else:
                y_processed = android_clahe_native_y(y_roi, float(clip), int(grid))
                rgb_processed = enhanced_rgb_from_stored(rgb_roi, y_roi, y_processed)
                applied = True

            tensor = resize_bilinear_android(rgb_processed)[None, ...].astype(np.float32)
            interpreter.set_tensor(inp["index"], tensor)
            interpreter.invoke()
            scores = np.asarray(interpreter.get_tensor(outp["index"]), dtype=np.float32).reshape(-1)
            if scores.size != 8 or not np.isfinite(scores).all():
                raise RuntimeError("Invalid model output for %s/%s/%s" % (row["device"], row["sample_id"], cid))
            p = int(np.argmax(scores))
            pred_by_config[cid][i] = p
            prediction_rows.append({
                "config_id": cid,
                "clip_limit": "" if clip is None else float(clip),
                "grid": "" if grid is None else int(grid),
                "device": str(row["device"]),
                "sample_id": str(row["sample_id"]),
                "class_label": str(row["class_label"]),
                "focus_condition": str(row["focus_condition"]),
                "repeat_index": int(row["repeat_index"]),
                "roi_mean_y_raw": float(row["roi_mean_y_raw"]),
                "processed_mean_y": float(np.mean(y_processed)),
                "processed_laplacian_variance": laplacian_variance4(y_processed),
                "source_rgb_clipped_pixel_fraction": clipped_fraction,
                "clahe_applied": applied,
                "predicted_class": LABELS[p],
                "correct": bool(p == true_idx[i]),
                "top1_score": float(scores[p]),
                **{"score_" + LABELS[j]: float(scores[j]) for j in range(8)},
            })

    pred_df = pd.DataFrame(prediction_rows)
    pred_df.to_csv(out / "clahe_predictions.csv", index=False)

    summary_rows = []
    per_rows = []
    diag_rows = []
    for cid, clip, grid in CONFIGS:
        cm, sm, per = cm_metrics(true_idx, pred_by_config[cid])
        summary_rows.append({"config_id": cid, "clip_limit": clip, "grid": grid, **sm})
        per.insert(0, "config_id", cid)
        per_rows.append(per)
        cm_df = pd.DataFrame(cm, index=LABELS, columns=LABELS)
        cm_df.index.name = "true_class"
        cm_df.to_csv(out / ("confusion_%s.csv" % cid))

        for scope, col in [("device", "device"), ("focus", "focus_condition")]:
            for val, idx_group in dim.groupby(col, sort=True).groups.items():
                idxs = np.array(sorted(idx_group), dtype=np.int64)
                _, dsm, _ = cm_metrics(true_idx[idxs], pred_by_config[cid][idxs])
                diag_rows.append({"config_id": cid, "scope": scope, "group": str(val), **dsm})

    summary = pd.DataFrame(summary_rows)
    perclass = pd.concat(per_rows, ignore_index=True)
    diagnostics = pd.DataFrame(diag_rows)

    deltas = paired_bootstrap(dim, true_idx, pred_by_config, args.bootstrap_iterations, args.bootstrap_seed)
    baseline_f1 = float(summary.loc[summary["config_id"].eq("none"), "macro_f1"].iloc[0])
    boot_rows = []
    boot_full_rows = []
    for cid, clip, grid in CONFIGS:
        if cid == "none":
            continue
        arr = deltas[cid]
        lo, hi = np.percentile(arr, [2.5, 97.5])
        point = float(summary.loc[summary["config_id"].eq(cid), "macro_f1"].iloc[0] - baseline_f1)
        min_recall = float(summary.loc[summary["config_id"].eq(cid), "min_recall"].iloc[0])
        eligible = bool(lo > 0.0 and min_recall > 0.0)
        boot_rows.append({
            "config_id": cid,
            "clip_limit": clip,
            "grid": grid,
            "baseline_macro_f1": baseline_f1,
            "config_macro_f1": float(summary.loc[summary["config_id"].eq(cid), "macro_f1"].iloc[0]),
            "delta_macro_f1": point,
            "ci95_lower": float(lo),
            "ci95_upper": float(hi),
            "min_class_recall": min_recall,
            "eligible": eligible,
        })
        for b, val in enumerate(arr):
            boot_full_rows.append({"bootstrap_iteration": b, "config_id": cid, "delta_macro_f1": float(val)})

    boot = pd.DataFrame(boot_rows)
    eligible = boot[boot["eligible"]].copy()
    if eligible.empty:
        decision_status = "no_clahe_configuration_passed"
        selected = "none"
        clahe_enabled = False
        parity_required = False
    else:
        max_f1 = float(eligible["config_macro_f1"].max())
        winners = eligible[np.isclose(eligible["config_macro_f1"], max_f1, rtol=0.0, atol=EPS)]
        if len(winners) == 1:
            selected = str(winners.iloc[0]["config_id"])
            decision_status = "selected_unique_eligible_clahe"
            clahe_enabled = True
            parity_required = True
        else:
            selected = None
            decision_status = "eligible_clahe_tie_requires_explicit_resolution"
            clahe_enabled = None
            parity_required = True

    summary.to_csv(out / "clahe_summary.csv", index=False)
    perclass.to_csv(out / "clahe_per_class.csv", index=False)
    diagnostics.to_csv(out / "clahe_diagnostics.csv", index=False)
    boot.to_csv(out / "clahe_bootstrap_summary.csv", index=False)
    pd.DataFrame(boot_full_rows).to_csv(out / "clahe_bootstrap_deltas.csv", index=False)

    decision = {
        "status": decision_status,
        "selection_basis": "95% paired stratified bootstrap CI(delta macro-F1 vs none) lower > 0 AND no class recall zero; highest observed macro-F1 among eligible; no hidden tie-break",
        "evaluation_population": "160 physically labelled redup quality samples; includes tajam and blur as specified by the calibration condition",
        "baseline_macro_f1": baseline_f1,
        "selected_config_id": selected,
        "clahe_enabled": clahe_enabled,
        "selected_clip_limit": None,
        "selected_grid": None,
        "requires_android_parity_confirmation": parity_required,
        "offline_reconstruction_method": validation["reconstruction_method"],
    }
    if selected and selected != "none":
        row = boot[boot["config_id"].eq(selected)].iloc[0]
        decision["selected_clip_limit"] = float(row["clip_limit"])
        decision["selected_grid"] = int(row["grid"])

    (out / "clahe_decision.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    validation = dict(validation)
    validation["tflite_runtime"] = runtime_name
    (out / "input_identity.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    output_names = [
        "clahe_predictions.csv", "clahe_summary.csv", "clahe_per_class.csv",
        "clahe_diagnostics.csv", "clahe_bootstrap_summary.csv", "clahe_bootstrap_deltas.csv",
        "clahe_decision.json", "input_identity.json",
    ] + ["confusion_%s.csv" % cid for cid, _, _ in CONFIGS]
    lock = {
        "status": "clahe_evaluation_evidence_locked",
        "stage6_lock_sha256": stage6["lock_sha256"],
        "stage6_evidence_sha256": stage6["evidence_sha256"],
        "stage6_sample_predictions_sha256": stage6["sample_sha256"],
        "model_sha256": android["model_sha256"],
        "android_source_hashes": android["source_hashes"],
        "bootstrap": validation["bootstrap"],
        "reconstruction_method": validation["reconstruction_method"],
        "decision_status": decision_status,
        "selected_config_id": selected,
        "requires_android_parity_confirmation": parity_required,
        "output_sha256": {name: sha256_file(out / name) for name in output_names},
    }
    (out / "clahe_evaluation_lock.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n=== CLAHE EVALUATION ===")
    print(summary[["config_id", "macro_f1", "min_recall", "accuracy"]].to_string(index=False))
    print("\n=== PAIRED BOOTSTRAP VS NONE ===")
    print(boot.to_string(index=False))
    print("decision_status=%s" % decision_status)
    print("selected_config_id=%s" % selected)
    print("Wrote: %s" % out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--poco", required=True, type=Path)
    p.add_argument("--redmi", required=True, type=Path)
    p.add_argument("--android", required=True, type=Path)
    p.add_argument("--lighting-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--bootstrap-iterations", type=int, default=2000)
    p.add_argument("--bootstrap-seed", type=int, default=42)
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()
    if args.bootstrap_iterations < 100:
        raise RuntimeError("Use at least 100 bootstrap iterations; thesis workflow defaults to 2000")

    stage6, android, sources, validation = validate_inputs(args)
    try:
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        if args.validate_only:
            print("VALIDATION_STATUS=READY_FOR_CLAHE_EVALUATION")
            return
        run_full(args, stage6, android, sources, validation)
    finally:
        for src in sources.values():
            src.close()


if __name__ == "__main__":
    main()
