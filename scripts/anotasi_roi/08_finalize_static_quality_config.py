#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError("Berkas tidak ditemukan: %s" % path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise RuntimeError(
            "%s tidak cocok.\nexpected=%r\nactual=%r"
            % (label, expected, actual)
        )


def verify_lock_outputs(stage_dir: Path, lock: Dict[str, Any], label: str) -> None:
    outputs = lock.get("output_sha256", {})
    if not outputs:
        raise RuntimeError("%s tidak memiliki output_sha256." % label)

    mismatches = []
    for name, expected in outputs.items():
        p = stage_dir / name
        if not p.is_file():
            mismatches.append("%s: missing" % name)
            continue
        actual = sha256_file(p)
        if actual != expected:
            mismatches.append(
                "%s: expected=%s actual=%s" % (name, expected, actual)
            )

    if mismatches:
        raise RuntimeError(
            "%s gagal verifikasi hash:\n%s"
            % (label, "\n".join(mismatches))
        )


def resolve_blur_candidate(evidence: Dict[str, Any]) -> Dict[str, Any]:
    candidates = evidence.get("argmax_candidates", [])
    if not candidates:
        raise RuntimeError("Tidak ada kandidat argmax blur.")

    max_j = max(float(x["youden_j"]) for x in candidates)
    eps = 1e-12
    tied = [
        x for x in candidates
        if abs(float(x["youden_j"]) - max_j) <= eps
    ]

    trace: List[Dict[str, Any]] = [
        {
            "priority": 1,
            "criterion": "maximize_youden_j",
            "best_value": max_j,
            "candidate_thresholds_after": [
                float(x["threshold"]) for x in tied
            ],
        }
    ]

    if len(tied) > 1:
        best_min = max(
            float(x["min_sensitivity_specificity"])
            for x in tied
        )
        tied = [
            x for x in tied
            if abs(
                float(x["min_sensitivity_specificity"]) - best_min
            ) <= eps
        ]
        trace.append(
            {
                "priority": 2,
                "criterion": "maximize_min_sensitivity_specificity",
                "best_value": best_min,
                "candidate_thresholds_after": [
                    float(x["threshold"]) for x in tied
                ],
            }
        )

    if len(tied) > 1:
        best_gap = min(
            float(x["abs_sensitivity_specificity_gap"])
            for x in tied
        )
        tied = [
            x for x in tied
            if abs(
                float(x["abs_sensitivity_specificity_gap"]) - best_gap
            ) <= eps
        ]
        trace.append(
            {
                "priority": 3,
                "criterion": "minimize_abs_sensitivity_specificity_gap",
                "best_value": best_gap,
                "candidate_thresholds_after": [
                    float(x["threshold"]) for x in tied
                ],
            }
        )

    if len(tied) > 1:
        lowest = min(float(x["threshold"]) for x in tied)
        tied = [
            x for x in tied
            if abs(float(x["threshold"]) - lowest) <= eps
        ]
        trace.append(
            {
                "priority": 4,
                "criterion": "lower_threshold_to_favor_sharp_sensitivity",
                "best_value": lowest,
                "candidate_thresholds_after": [
                    float(x["threshold"]) for x in tied
                ],
            }
        )

    if len(tied) != 1:
        raise RuntimeError(
            "Tie blur masih belum terselesaikan secara deterministik."
        )

    return {
        "selected": tied[0],
        "trace": trace,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalize static ROI/blur/lighting/CLAHE calibration."
    )
    parser.add_argument("--roi-eval-dir", type=Path, required=True)
    parser.add_argument("--blur-dir", type=Path, required=True)
    parser.add_argument("--lighting-dir", type=Path, required=True)
    parser.add_argument("--clahe-dir", type=Path, required=True)
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    roi_dir = args.roi_eval_dir
    blur_dir = args.blur_dir
    lighting_dir = args.lighting_dir
    clahe_dir = args.clahe_dir
    android_dir = args.android
    out_dir = args.out

    # Stage 4
    roi_decision_path = roi_dir / "roi_selection_decision.json"
    roi_lock_path = roi_dir / "roi_model_evaluation_lock.json"
    roi_decision = read_json(roi_decision_path)
    roi_lock = read_json(roi_lock_path)
    verify_lock_outputs(roi_dir, roi_lock, "Stage 4")

    selected_roi = float(roi_decision["selected_roi_width_fraction"])
    require_equal(
        float(roi_lock["selected_roi_width_fraction"]),
        selected_roi,
        "Stage 4 selected ROI",
    )

    # Stage 5
    blur_evidence_path = blur_dir / "blur_threshold_evidence.json"
    blur_lock_path = blur_dir / "blur_calibration_evidence_lock.json"
    blur_identity_path = blur_dir / "input_identity.json"
    blur_evidence = read_json(blur_evidence_path)
    blur_lock = read_json(blur_lock_path)
    blur_identity = read_json(blur_identity_path)
    verify_lock_outputs(blur_dir, blur_lock, "Stage 5")

    require_equal(
        float(blur_evidence["selected_roi_width_fraction"]),
        selected_roi,
        "Stage 5 ROI",
    )

    # Stage 6
    lighting_evidence_path = lighting_dir / "lighting_threshold_evidence.json"
    lighting_lock_path = lighting_dir / "lighting_calibration_evidence_lock.json"
    lighting_evidence = read_json(lighting_evidence_path)
    lighting_lock = read_json(lighting_lock_path)
    verify_lock_outputs(lighting_dir, lighting_lock, "Stage 6")

    require_equal(
        float(lighting_evidence["selected_roi_width_fraction"]),
        selected_roi,
        "Stage 6 ROI",
    )

    if lighting_evidence.get("selection_status") != \
            "selected_unique_macro_f1_maximum":
        raise RuntimeError(
            "Stage 6 belum mempunyai maksimum macro-F1 unik."
        )

    # Stage 7
    clahe_decision_path = clahe_dir / "clahe_decision.json"
    clahe_lock_path = clahe_dir / "clahe_evaluation_lock.json"
    clahe_decision = read_json(clahe_decision_path)
    clahe_lock = read_json(clahe_lock_path)
    verify_lock_outputs(clahe_dir, clahe_lock, "Stage 7")

    if bool(clahe_decision.get("clahe_enabled")):
        raise RuntimeError(
            "CLAHE terpilih. Blur raw-Y tidak boleh dikunci sebelum "
            "Android parity/recalibration selesai."
        )

    if clahe_decision.get("status") != "no_clahe_configuration_passed":
        raise RuntimeError(
            "Status Stage 7 tidak sesuai jalur tanpa CLAHE."
        )

    # Resolve the already-known Stage 5 Youden tie explicitly.
    blur_resolution = resolve_blur_candidate(blur_evidence)
    blur_selected = blur_resolution["selected"]

    aspect_ratio = float(blur_identity["aspect_ratio"])
    height_cap = float(blur_identity["height_cap_fraction"])
    blur_min = float(blur_selected["threshold"])
    luma_min = float(lighting_evidence["selected_luma_min"])
    luma_max = float(lighting_evidence["selected_luma_max"])

    if not (0.0 < selected_roi <= 1.0):
        raise RuntimeError("ROI fraction di luar rentang.")
    if not (0.0 < luma_min < luma_max < 255.0):
        raise RuntimeError("Ambang luminansi tidak valid.")
    if blur_min <= 0.0:
        raise RuntimeError("Ambang blur tidak valid.")

    # Inspect current Android source, but do not modify it.
    app_config_path = (
        android_dir / "app/src/main/assets/app_config.json"
    )
    quality_gate_path = (
        android_dir
        / "app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt"
    )

    app_config = read_json(app_config_path)
    if not quality_gate_path.is_file():
        raise FileNotFoundError(
            "QualityGate.kt tidak ditemukan: %s" % quality_gate_path
        )

    quality_text = quality_gate_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    current_lighting_before_blur = (
        quality_text.find("processedMean > config.lumaMax") != -1
        and quality_text.find("variance < config.blurMin") != -1
        and quality_text.find("processedMean > config.lumaMax")
        < quality_text.find("variance < config.blurMin")
    )

    current_clahe_branch = (
        "val enhanced = config.clahe" in quality_text
        and "clahe.apply" in quality_text
    )

    source_alignment = {
        "current_app_config_status": app_config.get("status"),
        "current_app_config_revision": app_config.get("revision"),
        "current_qualitygate_sha256": sha256_file(quality_gate_path),
        "current_app_config_sha256": sha256_file(app_config_path),
        "current_lighting_reason_before_blur": current_lighting_before_blur,
        "current_clahe_branch_present": current_clahe_branch,
        "alignment_required_before_sequence_collection": (
            current_lighting_before_blur
            or bool(app_config.get("clahe_enabled"))
            or abs(float(app_config.get("roi_width_fraction", -1.0))
                   - selected_roi) > 1e-12
            or abs(float(app_config.get("blur_variance_min", -1.0))
                   - blur_min) > 1e-12
            or abs(float(app_config.get("luma_min", -1.0))
                   - luma_min) > 1e-12
            or abs(float(app_config.get("luma_max", -1.0))
                   - luma_max) > 1e-12
        ),
    }

    static_config = {
        "status": "static_quality_calibrated",
        "roi_width_fraction": selected_roi,
        "roi_aspect_ratio": aspect_ratio,
        "roi_height_cap_fraction": height_cap,
        "blur_variance_min": blur_min,
        "blur_selection": {
            "youden_j": float(blur_selected["youden_j"]),
            "sensitivity": float(blur_selected["sensitivity"]),
            "specificity": float(blur_selected["specificity"]),
            "tie_resolution_rule": [
                "maximize Youden J",
                "then maximize min(sensitivity, specificity)",
                "then minimize |sensitivity-specificity|",
                "then lower threshold to favor sharp sensitivity",
            ],
            "decision_trace": blur_resolution["trace"],
        },
        "luma_min": luma_min,
        "luma_max": luma_max,
        "lighting_macro_f1": float(
            lighting_evidence["max_macro_f1"]
        ),
        "clahe_enabled": False,
        "clahe_clip_limit": None,
        "clahe_grid": None,
        "yuv_range": app_config.get("yuv_range", "limited_bt601"),
        "scope_note": (
            "Static image-quality parameters only. analysis_fps, "
            "confidence_threshold, temporal_window_ms, and "
            "minimum_results remain pending later calibration."
        ),
    }

    dependency_hashes = {
        "stage4_roi_decision_sha256": sha256_file(
            roi_decision_path
        ),
        "stage4_lock_sha256": sha256_file(roi_lock_path),
        "stage5_blur_evidence_sha256": sha256_file(
            blur_evidence_path
        ),
        "stage5_lock_sha256": sha256_file(blur_lock_path),
        "stage6_lighting_evidence_sha256": sha256_file(
            lighting_evidence_path
        ),
        "stage6_lock_sha256": sha256_file(lighting_lock_path),
        "stage7_clahe_decision_sha256": sha256_file(
            clahe_decision_path
        ),
        "stage7_lock_sha256": sha256_file(clahe_lock_path),
    }

    decision = {
        "status": "static_quality_ready_to_lock",
        "static_config": static_config,
        "dependencies": dependency_hashes,
        "android_source_alignment": source_alignment,
        "important_rule": (
            "CLAHE is disabled because no tested configuration "
            "satisfied the predeclared 95% CI improvement rule. "
            "Therefore the raw-Y blur calibration remains applicable."
        ),
    }

    print(json.dumps(decision, indent=2, ensure_ascii=False))

    if args.validate_only:
        print("\nVALIDATION_STATUS=READY_TO_LOCK_STATIC_QUALITY")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    config_path = out_dir / "static_quality_config.json"
    decision_path = out_dir / "static_quality_decision.json"
    patch_path = out_dir / "android_app_config_patch.json"

    write_json(config_path, static_config)
    write_json(decision_path, decision)

    # Patch intentionally contains only fields established by static calibration.
    patch = {
        "status": "static_quality_calibrated_postinfer_pending",
        "revision": "calib-static-001-no-clahe",
        "roi_width_fraction": selected_roi,
        "roi_aspect_ratio": aspect_ratio,
        "blur_variance_min": blur_min,
        "luma_min": luma_min,
        "luma_max": luma_max,
        "clahe_enabled": False,
        "note": (
            "Static ROI/blur/lighting/CLAHE calibration locked. "
            "Post-inference parameters and analysis FPS are still pending."
        ),
    }
    write_json(patch_path, patch)

    lock = {
        "status": "static_quality_config_locked",
        "dependencies": dependency_hashes,
        "selected_values": {
            "roi_width_fraction": selected_roi,
            "roi_aspect_ratio": aspect_ratio,
            "roi_height_cap_fraction": height_cap,
            "blur_variance_min": blur_min,
            "luma_min": luma_min,
            "luma_max": luma_max,
            "clahe_enabled": False,
        },
        "android_alignment_required_before_sequence_collection":
            source_alignment[
                "alignment_required_before_sequence_collection"
            ],
        "output_sha256": {
            "static_quality_config.json": sha256_file(config_path),
            "static_quality_decision.json": sha256_file(decision_path),
            "android_app_config_patch.json": sha256_file(patch_path),
        },
    }

    lock_path = out_dir / "static_quality_config_lock.json"
    write_json(lock_path, lock)

    print("\nSTATIC_QUALITY_CONFIG_LOCKED")
    print("Wrote: %s" % out_dir)


if __name__ == "__main__":
    main()
