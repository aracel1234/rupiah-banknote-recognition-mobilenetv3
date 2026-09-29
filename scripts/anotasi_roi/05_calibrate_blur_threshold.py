#!/usr/bin/env python3
"""Stage 5: calibrate blur threshold after ROI selection.

This stage intentionally uses RAW luminance ROI before CLAHE and before any
lighting/confidence/temporal gate. The Laplacian variance kernel mirrors the
4-neighbour implementation in Android QualityGate.kt.

Inputs may be directories or ZIP archives.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

import numpy as np
import pandas as pd
from PIL import Image


QUALITY_CLASSES = ["1000", "2000", "5000", "10000", "20000", "50000", "100000", "nonuang"]
LIGHTING = ["redup", "normal", "terang"]
FOCUS = ["tajam", "blur"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Source:
    raw: Path
    is_zip: bool
    prefix: str = ""
    zf: zipfile.ZipFile | None = None

    @classmethod
    def open(cls, value: str) -> "Source":
        p = Path(value).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Input tidak ditemukan: {p}")
        if p.is_dir():
            return cls(p, False)
        if zipfile.is_zipfile(p):
            return cls(p, True, zf=zipfile.ZipFile(p, "r"))
        raise ValueError(f"Input harus direktori atau ZIP: {p}")

    def close(self) -> None:
        if self.zf is not None:
            self.zf.close()

    def _names(self) -> list[str]:
        assert self.zf is not None
        return self.zf.namelist()

    def find_unique_suffix(self, suffix: str) -> str:
        suffix = suffix.replace("\\", "/")
        if self.is_zip:
            matches = [n for n in self._names() if n == suffix or n.endswith("/" + suffix)]
            if len(matches) != 1:
                raise RuntimeError(f"Harus tepat satu {suffix} dalam {self.raw}; ditemukan {len(matches)}")
            return matches[0]
        matches = [p for p in self.raw.rglob(Path(suffix).name) if p.as_posix().endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"Harus tepat satu {suffix} dalam {self.raw}; ditemukan {len(matches)}")
        return str(matches[0].relative_to(self.raw)).replace("\\", "/")

    def read(self, rel: str) -> bytes:
        rel = rel.replace("\\", "/")
        if self.is_zip:
            assert self.zf is not None
            return self.zf.read(rel)
        return (self.raw / rel).read_bytes()

    def exists(self, rel: str) -> bool:
        rel = rel.replace("\\", "/")
        if self.is_zip:
            return rel in set(self._names())
        return (self.raw / rel).exists()


def json_load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_output_hashes(eval_dir: Path) -> None:
    lock = json_load(eval_dir / "roi_model_evaluation_lock.json")
    for name, expected in lock.get("output_sha256", {}).items():
        p = eval_dir / name
        if not p.exists():
            raise RuntimeError(f"Stage 4 output hilang: {p}")
        got = sha256_file(p)
        if got != expected:
            raise RuntimeError(f"Hash Stage 4 berubah: {name}\nexpected={expected}\nactual={got}")


def parse_manifest(src: Source) -> tuple[str, list[dict[str, str]], str]:
    manifest_rel = src.find_unique_suffix("manifest.csv")
    data = src.read(manifest_rel)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    return manifest_rel, rows, sha256_bytes(data)


def resolve_manifest_file(manifest_rel: str, relative_path: str) -> str:
    parent = str(PurePosixPath(manifest_rel).parent)
    if parent == ".":
        return relative_path.replace("\\", "/")
    normalized_relative_path = relative_path.replace("\\", "/")
    return f"{parent}/{normalized_relative_path}"


def kotlin_round_to_int_positive(x: float) -> int:
    # Android dimensions/coordinates here are non-negative. Kotlin roundToInt()
    # follows round-to-nearest with .5 toward +infinity for positive numbers.
    return int(math.floor(float(x) + 0.5))


def roi_rect(width: int, height: int, fraction: float, aspect: float, height_cap: float) -> tuple[int, int, int, int]:
    # Mirror Float arithmetic used by RoiGeometry.kt as closely as possible.
    wf = np.float32(width) * np.float32(fraction)
    capped = np.float32(height) * np.float32(height_cap) * np.float32(aspect)
    w = np.float32(min(float(wf), float(capped)))
    h = np.float32(w / np.float32(aspect))
    left_f = np.float32((np.float32(width) - w) / np.float32(2.0))
    top_f = np.float32((np.float32(height) - h) / np.float32(2.0))
    right_f = np.float32((np.float32(width) + w) / np.float32(2.0))
    bottom_f = np.float32((np.float32(height) + h) / np.float32(2.0))
    left = max(0, min(width - 1, kotlin_round_to_int_positive(float(left_f))))
    top = max(0, min(height - 1, kotlin_round_to_int_positive(float(top_f))))
    right = min(width, kotlin_round_to_int_positive(float(right_f)))
    bottom = min(height, kotlin_round_to_int_positive(float(bottom_f)))
    if right - left < 3 or bottom - top < 3:
        raise RuntimeError(f"ROI terlalu kecil: {(left, top, right, bottom)}")
    return left, top, right, bottom


def laplacian_variance_exact(y: np.ndarray) -> float:
    """Exact-equivalent arithmetic for integer-valued FloatArray Y.

    QualityGate.kt uses y[left]+y[right]+y[up]+y[down]-4*y[center],
    then population variance over interior pixels. PNG luminance values are
    integer 0..255, so int64 accumulation is exact and maps to the same result.
    """
    if y.ndim != 2 or y.shape[0] < 3 or y.shape[1] < 3:
        raise ValueError("ROI luminance minimal 3x3")
    a = y.astype(np.int32, copy=False)
    lap = (
        a[1:-1, :-2]
        + a[1:-1, 2:]
        + a[:-2, 1:-1]
        + a[2:, 1:-1]
        - 4 * a[1:-1, 1:-1]
    ).astype(np.int64, copy=False)
    n = int(lap.size)
    s = int(lap.sum(dtype=np.int64))
    sq = int((lap * lap).sum(dtype=np.int64))
    average = s / n
    return max(0.0, sq / n - average * average)


def read_luma_png(raw: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(raw)) as im:
        # Collector stores the same Y value in RGB(A); L gives the channel value.
        arr = np.asarray(im.convert("L"), dtype=np.uint8)
    return arr


def validate_quality_balance(rows: list[dict[str, str]], device_name: str) -> list[dict[str, str]]:
    q = [r for r in rows if r.get("experiment_group") == "quality"]
    if len(q) != 240:
        raise RuntimeError(f"{device_name}: quality harus 240, ditemukan {len(q)}")
    counts: dict[tuple[str, str, str], int] = {}
    for r in q:
        key = (r.get("class_label", ""), r.get("lighting", ""), r.get("focus_condition", ""))
        counts[key] = counts.get(key, 0) + 1
    expected = {(c, l, f): 5 for c in QUALITY_CLASSES for l in LIGHTING for f in FOCUS}
    if counts != expected:
        missing = {k: v for k, v in expected.items() if counts.get(k) != v}
        extra = {k: v for k, v in counts.items() if expected.get(k) != v}
        raise RuntimeError(f"{device_name}: distribusi quality tidak seimbang. missing/wrong={missing}, extra={extra}")
    return q


def load_android_source_hashes(src: Source) -> dict[str, str]:
    result = {}
    for suffix in [
        "app/src/main/java/id/ac/ub/rupiah/image/RoiGeometry.kt",
        "app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt",
        "app/src/main/assets/app_config.json",
    ]:
        rel = src.find_unique_suffix(suffix)
        result[Path(suffix).name] = sha256_bytes(src.read(rel))
    return result


def inspect_qualitygate_semantics(src: Source) -> dict[str, object]:
    rel = src.find_unique_suffix("app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt")
    text = src.read(rel).decode("utf-8")
    kernel_tokens = ["y[i - 1]", "y[i + 1]", "y[i - width]", "y[i + width]", "4 * y[i]"]
    if not all(t in text for t in kernel_tokens):
        raise RuntimeError("Kernel Laplacian QualityGate.kt tidak sesuai pola 4-neighbour yang diharapkan.")
    return {
        "quality_gate_path": rel,
        "four_neighbor_laplacian_detected": True,
        "clahe_before_variance_in_current_source": text.find("clahe.apply") != -1 and text.find("clahe.apply") < text.find("laplacianVariance"),
        "reason_lighting_before_blur_in_current_source": (
            text.find("processedMean > config.lumaMax") != -1
            and text.find("variance < config.blurMin") != -1
            and text.find("processedMean > config.lumaMax") < text.find("variance < config.blurMin")
        ),
        "calibration_semantics": "raw luminance ROI; no CLAHE; no luma gate; sharp accepted iff variance >= T",
    }


def build_threshold_table(scores: pd.DataFrame) -> pd.DataFrame:
    values = scores["laplacian_variance"].to_numpy(dtype=float)
    truth_sharp = scores["focus_condition"].eq("tajam").to_numpy()
    unique = np.unique(values)
    unique.sort()
    if len(unique) < 2:
        raise RuntimeError("Varians Laplacian tidak memiliki cukup nilai unik.")
    candidates = [float(np.nextafter(unique[0], -np.inf))]
    candidates += [float((a + b) / 2.0) for a, b in zip(unique[:-1], unique[1:])]
    candidates.append(float(np.nextafter(unique[-1], np.inf)))
    out = []
    for t in candidates:
        pred_sharp = values >= t
        tp = int(np.sum(pred_sharp & truth_sharp))
        fn = int(np.sum((~pred_sharp) & truth_sharp))
        tn = int(np.sum((~pred_sharp) & (~truth_sharp)))
        fp = int(np.sum(pred_sharp & (~truth_sharp)))
        sensitivity = tp / (tp + fn)
        specificity = tn / (tn + fp)
        youden = sensitivity + specificity - 1.0
        out.append({
            "threshold": t,
            "sensitivity": sensitivity,
            "specificity": specificity,
            "youden_j": youden,
            "balanced_accuracy": (sensitivity + specificity) / 2.0,
            "min_sensitivity_specificity": min(sensitivity, specificity),
            "abs_sensitivity_specificity_gap": abs(sensitivity - specificity),
            "tp_sharp_accepted": tp,
            "fn_sharp_rejected": fn,
            "tn_blur_rejected": tn,
            "fp_blur_accepted": fp,
        })
    df = pd.DataFrame(out)
    max_j = df["youden_j"].max()
    df["is_max_youden"] = np.isclose(df["youden_j"], max_j, atol=1e-15, rtol=0)
    return df


def distribution_table(scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = [
        ("overall_focus", ["focus_condition"]),
        ("device_focus", ["device", "focus_condition"]),
        ("lighting_focus", ["lighting", "focus_condition"]),
        ("device_lighting_focus", ["device", "lighting", "focus_condition"]),
    ]
    for scope, cols in group_cols:
        for keys, g in scores.groupby(cols, dropna=False, sort=True):
            if not isinstance(keys, tuple):
                keys = (keys,)
            values = g["laplacian_variance"].to_numpy(float)
            rec = {
                "scope": scope,
                "group": " | ".join(f"{c}={v}" for c, v in zip(cols, keys)),
                "n": len(g),
                "mean": float(np.mean(values)),
                "min": float(np.min(values)),
                "q1": float(np.quantile(values, 0.25)),
                "median": float(np.median(values)),
                "q3": float(np.quantile(values, 0.75)),
                "max": float(np.max(values)),
            }
            rows.append(rec)
    return pd.DataFrame(rows)


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poco", required=True)
    ap.add_argument("--redmi", required=True)
    ap.add_argument("--android", required=True)
    ap.add_argument("--roi-eval-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    eval_dir = args.roi_eval_dir.expanduser().resolve()
    if not eval_dir.is_dir():
        raise FileNotFoundError(f"Stage 4 directory tidak ditemukan: {eval_dir}")
    verify_output_hashes(eval_dir)
    stage4_lock = json_load(eval_dir / "roi_model_evaluation_lock.json")
    decision = json_load(eval_dir / "roi_selection_decision.json")
    identity = json_load(eval_dir / "input_identity.json")
    if stage4_lock.get("status") != "roi_model_evaluation_complete":
        raise RuntimeError("Stage 4 belum complete.")
    selected = float(decision["selected_roi_width_fraction"])
    if selected != float(stage4_lock["selected_roi_width_fraction"]):
        raise RuntimeError("selected ROI tidak konsisten antara decision dan lock.")
    if selected != 0.9:
        raise RuntimeError(f"Script ini mengharapkan hasil Stage 4 saat ini r=0.9, ditemukan {selected}")
    aspect = float(identity["preprocess"]["aspect_ratio"])
    cap = float(identity["preprocess"]["height_cap_fraction"])

    poco = Source.open(args.poco)
    redmi = Source.open(args.redmi)
    android = Source.open(args.android)
    try:
        android_hashes = load_android_source_hashes(android)
        gate_semantics = inspect_qualitygate_semantics(android)
        sources = []
        quality_rows = []
        for device, src in [("poco", poco), ("redmi", redmi)]:
            manifest_rel, rows, manifest_sha = parse_manifest(src)
            expected_sha = identity[f"{device}_source"]["manifest_sha256"]
            if manifest_sha != expected_sha:
                raise RuntimeError(f"{device}: manifest berbeda dari input Stage 4")
            q = validate_quality_balance(rows, device)
            bad_hash = 0
            for r in q:
                rel = resolve_manifest_file(manifest_rel, r["relative_luma_path"])
                if not src.exists(rel):
                    raise FileNotFoundError(f"{device}: luma hilang {rel}")
                raw = src.read(rel)
                if sha256_bytes(raw) != r["luma_sha256"]:
                    bad_hash += 1
            if bad_hash:
                raise RuntimeError(f"{device}: {bad_hash} hash luma tidak cocok")
            sources.append({
                "device": device,
                "source_type": "zip" if src.is_zip else "directory",
                "path": str(src.raw),
                "manifest_path": manifest_rel,
                "manifest_sha256": manifest_sha,
                "quality_samples": len(q),
                "luma_hash_mismatches": 0,
            })
            quality_rows.append((device, src, manifest_rel, q))

        validation = {
            "status": "READY_FOR_BLUR_CALIBRATION",
            "selected_roi_width_fraction": selected,
            "aspect_ratio": aspect,
            "height_cap_fraction": cap,
            "total_quality_samples": sum(x["quality_samples"] for x in sources),
            "sharp_samples": 240,
            "blur_samples": 240,
            "sources": sources,
            "stage4_lock_sha256": sha256_file(eval_dir / "roi_model_evaluation_lock.json"),
            "stage4_decision_sha256": sha256_file(eval_dir / "roi_selection_decision.json"),
            "android_source_hashes": android_hashes,
            "qualitygate_semantics": gate_semantics,
            "method_boundary": "raw Y ROI only; CLAHE/luma thresholds/confidence/temporal smoothing are not applied",
        }
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        if args.validate_only:
            print("VALIDATION_STATUS=READY_FOR_BLUR_CALIBRATION")
            return 0

        records = []
        for device, src, manifest_rel, qrows in quality_rows:
            for r in qrows:
                rel = resolve_manifest_file(manifest_rel, r["relative_luma_path"])
                raw = src.read(rel)
                arr = read_luma_png(raw)
                h, w = arr.shape
                mw = int(r["oriented_width"])
                mh = int(r["oriented_height"])
                if (w, h) != (mw, mh):
                    raise RuntimeError(f"{device}/{r['sample_id']}: PNG {w}x{h} != manifest {mw}x{mh}")
                left, top, right, bottom = roi_rect(w, h, selected, aspect, cap)
                roi = arr[top:bottom, left:right]
                variance = laplacian_variance_exact(roi)
                mean_y = float(np.mean(roi, dtype=np.float64))
                records.append({
                    "device": device,
                    "sample_id": r["sample_id"],
                    "class_label": r["class_label"],
                    "lighting": r["lighting"],
                    "focus_condition": r["focus_condition"],
                    "repeat_index": int(r["repeat_index"]),
                    "frame_width": w,
                    "frame_height": h,
                    "roi_width_fraction": selected,
                    "roi_left": left,
                    "roi_top": top,
                    "roi_right": right,
                    "roi_bottom": bottom,
                    "roi_width": right - left,
                    "roi_height": bottom - top,
                    "roi_mean_y_raw": mean_y,
                    "laplacian_variance": variance,
                    "luma_png_sha256": r["luma_sha256"],
                })

        scores = pd.DataFrame(records)
        if len(scores) != 480 or scores.duplicated(["device", "sample_id"]).any():
            raise RuntimeError("Skor blur harus tepat 480 baris unik.")
        thresholds = build_threshold_table(scores)
        max_rows = thresholds[thresholds["is_max_youden"]].copy()
        dists = distribution_table(scores)

        # Do not silently resolve a primary Youden tie. We lock the evidence and
        # expose all argmax candidates for explicit methodological review.
        max_candidates = []
        for _, x in max_rows.iterrows():
            max_candidates.append({
                "threshold": float(x["threshold"]),
                "youden_j": float(x["youden_j"]),
                "sensitivity": float(x["sensitivity"]),
                "specificity": float(x["specificity"]),
                "min_sensitivity_specificity": float(x["min_sensitivity_specificity"]),
                "abs_sensitivity_specificity_gap": float(x["abs_sensitivity_specificity_gap"]),
                "tp_sharp_accepted": int(x["tp_sharp_accepted"]),
                "fn_sharp_rejected": int(x["fn_sharp_rejected"]),
                "tn_blur_rejected": int(x["tn_blur_rejected"]),
                "fp_blur_accepted": int(x["fp_blur_accepted"]),
            })

        out = args.out.expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        scores.to_csv(out / "blur_sample_scores.csv", index=False)
        thresholds.to_csv(out / "blur_threshold_candidates.csv", index=False)
        dists.to_csv(out / "blur_score_distributions.csv", index=False)

        evidence = {
            "status": "blur_youden_evidence_complete",
            "selected_roi_width_fraction": selected,
            "n_total": 480,
            "n_sharp": int(scores["focus_condition"].eq("tajam").sum()),
            "n_blur": int(scores["focus_condition"].eq("blur").sum()),
            "primary_rule": "maximize sensitivity(T) + specificity(T) - 1",
            "sharp_accept_rule": "laplacian_variance >= T",
            "max_youden_j": float(thresholds["youden_j"].max()),
            "argmax_candidate_count": len(max_candidates),
            "argmax_candidates": max_candidates,
            "selection_status": "unique" if len(max_candidates) == 1 else "tie_requires_explicit_resolution",
            "note": "No lower-level tie-break is silently applied when multiple thresholds share maximum Youden J.",
        }
        write_json(out / "blur_threshold_evidence.json", evidence)
        write_json(out / "input_identity.json", validation)

        output_names = [
            "blur_sample_scores.csv",
            "blur_threshold_candidates.csv",
            "blur_score_distributions.csv",
            "blur_threshold_evidence.json",
            "input_identity.json",
        ]
        lock = {
            "status": "blur_calibration_evidence_locked",
            "selected_roi_width_fraction": selected,
            "stage4_lock_sha256": validation["stage4_lock_sha256"],
            "stage4_decision_sha256": validation["stage4_decision_sha256"],
            "android_source_hashes": android_hashes,
            "method_boundary": validation["method_boundary"],
            "output_sha256": {name: sha256_file(out / name) for name in output_names},
        }
        write_json(out / "blur_calibration_evidence_lock.json", lock)

        print("\n=== BLUR YOUDEN EVIDENCE ===")
        print(f"n_total={len(scores)} sharp={int(scores['focus_condition'].eq('tajam').sum())} blur={int(scores['focus_condition'].eq('blur').sum())}")
        print(f"max_youden_j={evidence['max_youden_j']:.12f}")
        print(f"argmax_candidate_count={len(max_candidates)}")
        for c in max_candidates:
            print(
                "T={threshold:.12f} sensitivity={sensitivity:.6f} specificity={specificity:.6f} "
                "J={youden_j:.6f} TP={tp_sharp_accepted} FN={fn_sharp_rejected} "
                "TN={tn_blur_rejected} FP={fp_blur_accepted}".format(**c)
            )
        print(f"selection_status={evidence['selection_status']}")
        print(f"Wrote: {out}")
        return 0
    finally:
        poco.close(); redmi.close(); android.close()


if __name__ == "__main__":
    raise SystemExit(main())
