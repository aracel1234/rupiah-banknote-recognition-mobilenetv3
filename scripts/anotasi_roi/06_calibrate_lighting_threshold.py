#!/usr/bin/env python3
"""
Stage 6 - Calibration of lighting thresholds from raw ROI luminance.

Input:
  Stage 5 output directory containing:
    - blur_sample_scores.csv
    - blur_calibration_evidence_lock.json
    - input_identity.json

Method:
  - Uses roi_mean_y_raw from the selected ROI.
  - Does not apply blur filtering, CLAHE, confidence threshold, or temporal smoothing.
  - Predicts:
        mean_y < T_low  -> redup
        mean_y > T_high -> terang
        otherwise       -> normal
  - Exhaustively searches threshold pairs at midpoints between distinct observed
    mean-Y values.
  - Primary selection criterion: maximum macro F1 over {redup, normal, terang}.
  - If multiple pairs share the maximum within numerical tolerance, no hidden
    lower-level tie-break is applied.

Compatible with Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


LABELS = ("redup", "normal", "terang")
EPS = 1e-12


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def metrics_from_cm(cm: np.ndarray) -> dict:
    total = int(cm.sum())
    accuracy = safe_div(float(np.trace(cm)), float(total))

    precision = []
    recall = []
    f1 = []

    for i in range(len(LABELS)):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum() - tp)
        fn = int(cm[i, :].sum() - tp)

        p = safe_div(tp, tp + fp)
        r = safe_div(tp, tp + fn)
        f = safe_div(2.0 * p * r, p + r)

        precision.append(p)
        recall.append(r)
        f1.append(f)

    return {
        "accuracy": accuracy,
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
        "macro_f1": float(np.mean(f1)),
        "precision_redup": precision[0],
        "recall_redup": recall[0],
        "f1_redup": f1[0],
        "precision_normal": precision[1],
        "recall_normal": recall[1],
        "f1_normal": f1[1],
        "precision_terang": precision[2],
        "recall_terang": recall[2],
        "f1_terang": f1[2],
    }


def cm_for_thresholds(y: np.ndarray, true_idx: np.ndarray, low: float, high: float) -> np.ndarray:
    pred_idx = np.where(y < low, 0, np.where(y > high, 2, 1))
    cm = np.zeros((3, 3), dtype=np.int64)
    for t, p in zip(true_idx, pred_idx):
        cm[int(t), int(p)] += 1
    return cm


def validate_stage5(blur_dir: Path):
    sample_path = blur_dir / "blur_sample_scores.csv"
    lock_path = blur_dir / "blur_calibration_evidence_lock.json"
    identity_path = blur_dir / "input_identity.json"

    for p in (sample_path, lock_path, identity_path):
        if not p.is_file():
            raise FileNotFoundError("Required Stage 5 artifact not found: %s" % p)

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    identity = json.loads(identity_path.read_text(encoding="utf-8"))

    if lock.get("status") != "blur_calibration_evidence_locked":
        raise RuntimeError("Stage 5 lock status is not blur_calibration_evidence_locked")

    expected_sample_hash = lock.get("output_sha256", {}).get("blur_sample_scores.csv")
    actual_sample_hash = sha256_file(sample_path)

    if not expected_sample_hash or actual_sample_hash != expected_sample_hash:
        raise RuntimeError(
            "blur_sample_scores.csv hash does not match Stage 5 lock: expected=%s actual=%s"
            % (expected_sample_hash, actual_sample_hash)
        )

    df = pd.read_csv(sample_path)

    required = {
        "device", "sample_id", "class_label", "lighting", "focus_condition",
        "repeat_index", "roi_width_fraction", "roi_mean_y_raw",
        "laplacian_variance"
    }
    missing = sorted(required.difference(df.columns))
    if missing:
        raise RuntimeError("Missing required columns: %s" % ", ".join(missing))

    if len(df) != 480:
        raise RuntimeError("Expected 480 quality samples, found %d" % len(df))

    if df.duplicated(["device", "sample_id"]).any():
        raise RuntimeError("Duplicate (device, sample_id) rows found")

    if not set(df["lighting"].astype(str)).issubset(set(LABELS)):
        raise RuntimeError("Unexpected lighting labels")

    counts = df["lighting"].value_counts().to_dict()
    expected_counts = {"redup": 160, "normal": 160, "terang": 160}
    if counts != expected_counts:
        raise RuntimeError("Lighting balance mismatch: %r" % counts)

    device_counts = df["device"].value_counts().to_dict()
    if device_counts != {"poco": 240, "redmi": 240}:
        raise RuntimeError("Device balance mismatch: %r" % device_counts)

    focus_counts = df["focus_condition"].value_counts().to_dict()
    if focus_counts != {"tajam": 240, "blur": 240}:
        raise RuntimeError("Focus balance mismatch: %r" % focus_counts)

    y = df["roi_mean_y_raw"].to_numpy(dtype=np.float64)
    if not np.isfinite(y).all():
        raise RuntimeError("Non-finite roi_mean_y_raw detected")

    selected_roi = float(lock.get("selected_roi_width_fraction"))
    if not np.allclose(df["roi_width_fraction"].to_numpy(dtype=float), selected_roi, atol=1e-12):
        raise RuntimeError("ROI fraction in sample scores does not match Stage 5 lock")

    return df, lock, identity, sample_path, lock_path, identity_path


def exhaustive_search(df: pd.DataFrame) -> pd.DataFrame:
    y = df["roi_mean_y_raw"].to_numpy(dtype=np.float64)
    label_to_idx = {label: i for i, label in enumerate(LABELS)}
    true_idx = np.array([label_to_idx[str(x)] for x in df["lighting"]], dtype=np.int64)

    unique_values = np.unique(y)
    if len(unique_values) < 3:
        raise RuntimeError("Not enough distinct mean-Y values")

    thresholds = (unique_values[:-1] + unique_values[1:]) / 2.0

    # Build cumulative true-class counts at each threshold boundary.
    order = np.argsort(y, kind="mergesort")
    ys = y[order]
    ts = true_idx[order]

    # For each threshold, count samples strictly below it.
    cuts = np.searchsorted(ys, thresholds, side="left")
    prefix = np.zeros((len(ys) + 1, 3), dtype=np.int64)
    for i, t in enumerate(ts, start=1):
        prefix[i] = prefix[i - 1]
        prefix[i, int(t)] += 1
    totals = prefix[-1]

    rows = []
    for i in range(len(thresholds) - 1):
        low = float(thresholds[i])
        low_cut = int(cuts[i])
        dim_counts = prefix[low_cut]

        for j in range(i + 1, len(thresholds)):
            high = float(thresholds[j])
            high_cut = int(cuts[j])

            normal_counts = prefix[high_cut] - prefix[low_cut]
            bright_counts = totals - prefix[high_cut]

            # Rows=true class, columns=predicted lighting.
            cm = np.column_stack((dim_counts, normal_counts, bright_counts))
            m = metrics_from_cm(cm)

            rows.append({
                "luma_min_candidate": low,
                "luma_max_candidate": high,
                **m,
                "is_max_macro_f1": False,
            })

    out = pd.DataFrame(rows)
    max_f1 = float(out["macro_f1"].max())
    out.loc[np.isclose(out["macro_f1"], max_f1, rtol=0.0, atol=EPS), "is_max_macro_f1"] = True
    return out


def distribution_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    def add(scope: str, keys, group):
        v = group["roi_mean_y_raw"].to_numpy(dtype=float)
        if isinstance(keys, tuple):
            keyvals = keys
        else:
            keyvals = (keys,)
        rows.append({
            "scope": scope,
            "group": " | ".join(str(x) for x in keyvals),
            "n": len(v),
            "mean": float(np.mean(v)),
            "min": float(np.min(v)),
            "q1": float(np.quantile(v, 0.25)),
            "median": float(np.median(v)),
            "q3": float(np.quantile(v, 0.75)),
            "max": float(np.max(v)),
        })

    for light, g in df.groupby("lighting", sort=True):
        add("lighting", "lighting=%s" % light, g)

    for keys, g in df.groupby(["device", "lighting"], sort=True):
        add(
            "device_lighting",
            ("device=%s" % keys[0], "lighting=%s" % keys[1]),
            g,
        )

    for keys, g in df.groupby(["focus_condition", "lighting"], sort=True):
        add(
            "focus_lighting",
            ("focus_condition=%s" % keys[0], "lighting=%s" % keys[1]),
            g,
        )

    return pd.DataFrame(rows)


def diagnostics_for_pair(df: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    rows = []
    label_to_idx = {label: i for i, label in enumerate(LABELS)}

    def evaluate(scope: str, group_name: str, g: pd.DataFrame):
        y = g["roi_mean_y_raw"].to_numpy(dtype=float)
        true_idx = np.array([label_to_idx[str(x)] for x in g["lighting"]], dtype=np.int64)
        cm = cm_for_thresholds(y, true_idx, low, high)
        m = metrics_from_cm(cm)
        rows.append({"scope": scope, "group": group_name, "n": len(g), **m})

    evaluate("overall", "all", df)
    for dev, g in df.groupby("device", sort=True):
        evaluate("device", "device=%s" % dev, g)
    for focus, g in df.groupby("focus_condition", sort=True):
        evaluate("focus", "focus_condition=%s" % focus, g)

    return pd.DataFrame(rows)


def predictions_for_pair(df: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    out = df.copy()
    y = out["roi_mean_y_raw"].to_numpy(dtype=float)
    pred = np.where(y < low, "redup", np.where(y > high, "terang", "normal"))
    out["predicted_lighting"] = pred
    out["lighting_correct"] = out["lighting"].astype(str).to_numpy() == pred
    out["luma_min"] = low
    out["luma_max"] = high
    return out


def confusion_dataframe(df: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    label_to_idx = {label: i for i, label in enumerate(LABELS)}
    y = df["roi_mean_y_raw"].to_numpy(dtype=float)
    true_idx = np.array([label_to_idx[str(x)] for x in df["lighting"]], dtype=np.int64)
    cm = cm_for_thresholds(y, true_idx, low, high)
    out = pd.DataFrame(cm, index=LABELS, columns=LABELS)
    out.index.name = "true_lighting"
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blur-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    df, stage5_lock, stage5_identity, sample_path, lock_path, identity_path = validate_stage5(args.blur_dir)

    validation = {
        "status": "READY_FOR_LIGHTING_CALIBRATION",
        "selected_roi_width_fraction": float(stage5_lock["selected_roi_width_fraction"]),
        "total_quality_samples": int(len(df)),
        "lighting_counts": {k: int(v) for k, v in df["lighting"].value_counts().sort_index().items()},
        "device_counts": {k: int(v) for k, v in df["device"].value_counts().sort_index().items()},
        "focus_counts": {k: int(v) for k, v in df["focus_condition"].value_counts().sort_index().items()},
        "stage5_lock_sha256": sha256_file(lock_path),
        "stage5_sample_scores_sha256": sha256_file(sample_path),
        "method_boundary": "raw mean Y on selected ROI; no blur filtering; no CLAHE; no confidence threshold; no temporal smoothing",
        "classification_rule": "redup if meanY < T_low; terang if meanY > T_high; otherwise normal",
        "primary_rule": "maximize macro F1 across redup, normal, terang",
    }

    print(json.dumps(validation, indent=2, ensure_ascii=False))

    if args.validate_only:
        print("VALIDATION_STATUS=READY_FOR_LIGHTING_CALIBRATION")
        return

    args.out.mkdir(parents=True, exist_ok=True)

    candidates = exhaustive_search(df)
    max_f1 = float(candidates["macro_f1"].max())
    winners = candidates[candidates["is_max_macro_f1"]].copy()

    candidates.to_csv(args.out / "lighting_threshold_candidates.csv", index=False)
    distribution_table(df).to_csv(args.out / "lighting_score_distributions.csv", index=False)

    evidence = {
        "status": "lighting_macro_f1_evidence_complete",
        "selected_roi_width_fraction": float(stage5_lock["selected_roi_width_fraction"]),
        "n_total": int(len(df)),
        "lighting_counts": {k: int(v) for k, v in df["lighting"].value_counts().sort_index().items()},
        "primary_rule": "maximize macro F1 across redup, normal, terang",
        "classification_rule": "redup if meanY < T_low; terang if meanY > T_high; otherwise normal",
        "max_macro_f1": max_f1,
        "argmax_candidate_count": int(len(winners)),
        "argmax_candidates": winners.drop(columns=["is_max_macro_f1"]).to_dict(orient="records"),
        "selection_status": "selected_unique_macro_f1_maximum" if len(winners) == 1 else "tie_requires_explicit_resolution",
        "method_boundary": validation["method_boundary"],
    }

    if len(winners) == 1:
        low = float(winners.iloc[0]["luma_min_candidate"])
        high = float(winners.iloc[0]["luma_max_candidate"])

        predictions_for_pair(df, low, high).to_csv(
            args.out / "lighting_sample_predictions.csv", index=False
        )
        confusion_dataframe(df, low, high).to_csv(
            args.out / "lighting_confusion_matrix.csv"
        )
        diagnostics_for_pair(df, low, high).to_csv(
            args.out / "lighting_diagnostics.csv", index=False
        )

        evidence["selected_luma_min"] = low
        evidence["selected_luma_max"] = high

    (args.out / "lighting_threshold_evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (args.out / "input_identity.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    output_names = [
        "lighting_threshold_candidates.csv",
        "lighting_score_distributions.csv",
        "lighting_threshold_evidence.json",
        "input_identity.json",
    ]
    if len(winners) == 1:
        output_names.extend([
            "lighting_sample_predictions.csv",
            "lighting_confusion_matrix.csv",
            "lighting_diagnostics.csv",
        ])

    output_hashes = {
        name: sha256_file(args.out / name)
        for name in output_names
    }

    lock = {
        "status": "lighting_calibration_evidence_locked",
        "selected_roi_width_fraction": float(stage5_lock["selected_roi_width_fraction"]),
        "stage5_lock_sha256": sha256_file(lock_path),
        "stage5_sample_scores_sha256": sha256_file(sample_path),
        "method_boundary": validation["method_boundary"],
        "classification_rule": validation["classification_rule"],
        "primary_rule": validation["primary_rule"],
        "selection_status": evidence["selection_status"],
        "output_sha256": output_hashes,
    }

    (args.out / "lighting_calibration_evidence_lock.json").write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("=== LIGHTING THRESHOLD EVIDENCE ===")
    print("n_total=%d" % len(df))
    print("max_macro_f1=%.12f" % max_f1)
    print("argmax_candidate_count=%d" % len(winners))

    for _, row in winners.iterrows():
        print(
            "T_low=%.12f T_high=%.12f macro_f1=%.12f accuracy=%.12f"
            % (
                row["luma_min_candidate"],
                row["luma_max_candidate"],
                row["macro_f1"],
                row["accuracy"],
            )
        )

    print("selection_status=%s" % evidence["selection_status"])
    print("Wrote: %s" % args.out)


if __name__ == "__main__":
    main()
