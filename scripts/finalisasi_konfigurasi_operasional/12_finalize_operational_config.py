#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def verify_output_hashes(stage_dir: Path, lock: Dict[str, Any], label: str) -> None:
    mismatches: List[str] = []
    for name, expected in lock.get("output_sha256", {}).items():
        p = stage_dir / name
        if not p.is_file():
            mismatches.append(f"{name}: missing")
            continue
        actual = sha256_file(p)
        if actual != expected:
            mismatches.append(f"{name}: expected={expected} actual={actual}")
    if mismatches:
        raise RuntimeError(label + " hash verification failed:\n" + "\n".join(mismatches))


def float_equal(a: Any, b: Any, atol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= atol


def require_float_equal(actual: Any, expected: Any, label: str) -> None:
    if not float_equal(actual, expected):
        raise RuntimeError(f"{label} mismatch: actual={actual!r} expected={expected!r}")


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def as_bool(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Finalize one operational configuration from locked static-quality and sequence calibration evidence."
    )
    ap.add_argument("--static-dir", type=Path, required=True)
    ap.add_argument("--sequence-audit-dir", type=Path, required=True)
    ap.add_argument("--postinfer-dir", type=Path, required=True)
    ap.add_argument("--android", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    static_dir = args.static_dir
    seq_audit_dir = args.sequence_audit_dir
    post_dir = args.postinfer_dir
    android = args.android

    # ---------- Static-quality evidence ----------
    static_cfg_path = static_dir / "static_quality_config.json"
    static_lock_path = static_dir / "static_quality_config_lock.json"
    static_cfg = read_json(static_cfg_path)
    static_lock = read_json(static_lock_path)
    verify_output_hashes(static_dir, static_lock, "Static-quality stage")

    selected_static = static_lock["selected_values"]
    for key in (
        "roi_width_fraction",
        "roi_aspect_ratio",
        "roi_height_cap_fraction",
        "blur_variance_min",
        "luma_min",
        "luma_max",
    ):
        require_float_equal(static_cfg[key], selected_static[key], f"static {key}")
    if bool(static_cfg["clahe_enabled"]) != bool(selected_static["clahe_enabled"]):
        raise RuntimeError("static clahe_enabled mismatch")

    # ---------- Sequence input audit ----------
    seq_lock_path = seq_audit_dir / "sequence_input_lock.json"
    seq_audit_path = seq_audit_dir / "sequence_input_audit.json"
    seq_lock = read_json(seq_lock_path)
    seq_audit = read_json(seq_audit_path)
    verify_output_hashes(seq_audit_dir, seq_lock, "Sequence input audit")

    if seq_audit.get("status") != "ready_for_postinference_replay":
        raise RuntimeError("Sequence input audit is not ready.")
    if seq_lock.get("status") != "sequence_inputs_locked":
        raise RuntimeError("Sequence input lock is not locked.")

    # ---------- Post-inference calibration ----------
    post_lock_path = post_dir / "postinference_calibration_lock.json"
    decision_path = post_dir / "postinference_selection_decision.json"
    post_lock = read_json(post_lock_path)
    decision = read_json(decision_path)
    verify_output_hashes(post_dir, post_lock, "Post-inference calibration")

    actual_seq_lock_sha = sha256_file(seq_lock_path)
    if post_lock["sequence_input_lock_sha256"] != actual_seq_lock_sha:
        raise RuntimeError("Post-inference lock does not reference this sequence input lock.")
    if decision["sequence_input_lock_sha256"] != actual_seq_lock_sha:
        raise RuntimeError("Selection decision does not reference this sequence input lock.")
    if post_lock["analysis_plan_sha256"] != seq_lock["analysis_plan_sha256"]:
        raise RuntimeError("analysis_plan_sha256 mismatch between Stage 09 and Stage 10.")
    if decision["analysis_plan_sha256"] != seq_lock["analysis_plan_sha256"]:
        raise RuntimeError("Selection decision analysis plan mismatch.")

    selected = post_lock["selected_postinference"]
    if decision.get("selection_status") != "selected_unique_postinference_configuration":
        raise RuntimeError("Post-inference selection is not unique.")
    selected2 = decision["selected"]
    for key in (
        "analysis_fps",
        "confidence_threshold",
        "temporal_window_ms",
        "minimum_results",
        "mssr",
        "car",
        "war",
        "rr_nominal",
        "nonmoney_false_accept_rate",
        "median_decision_ms",
        "p95_decision_ms",
        "min_class_car",
    ):
        a = selected[key]
        b = selected2[key]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            require_float_equal(a, b, f"selected {key}")
        elif a != b:
            raise RuntimeError(f"selected {key} mismatch")

    if int(selected["analysis_fps"]) != int(seq_lock["selected_analysis_fps"]):
        raise RuntimeError("Selected FPS does not match the input-audit FPS lock.")

    # ---------- Current Android source must still be the source audited by Stage 09 ----------
    app_cfg_path = android / "app/src/main/assets/app_config.json"
    temporal_path = android / "app/src/main/java/id/ac/ub/rupiah/prediction/TemporalDecision.kt"
    session_path = android / "app/src/main/java/id/ac/ub/rupiah/session/RecognitionSession.kt"

    for p in (app_cfg_path, temporal_path, session_path):
        if not p.is_file():
            raise FileNotFoundError(p)

    expected_android_hashes = seq_lock["android_source_hashes"]
    actual_android_hashes = {
        "app_config.json": sha256_file(app_cfg_path),
        "TemporalDecision.kt": sha256_file(temporal_path),
        "RecognitionSession.kt": sha256_file(session_path),
    }
    for name, expected in expected_android_hashes.items():
        actual = actual_android_hashes[name]
        if actual != expected:
            raise RuntimeError(
                f"Android source changed since sequence calibration: {name}\n"
                f"expected={expected}\nactual={actual}"
            )

    app_cfg = read_json(app_cfg_path)

    # Static settings in the Android source used for sequence collection must match Stage 8.
    for key in (
        "roi_width_fraction",
        "roi_aspect_ratio",
        "roi_height_cap_fraction",
        "blur_variance_min",
        "luma_min",
        "luma_max",
    ):
        require_float_equal(app_cfg[key], selected_static[key], f"Android static {key}")
    if bool(app_cfg["clahe_enabled"]) != bool(selected_static["clahe_enabled"]):
        raise RuntimeError("Android static clahe_enabled does not match Stage 8.")
    if app_cfg.get("yuv_range") != static_cfg.get("yuv_range"):
        raise RuntimeError("Android yuv_range does not match Stage 8.")

    # ---------- Diagnostics for the selected candidate ----------
    cid = str(selected["candidate_id"])
    cand_rows = read_csv_rows(post_dir / "candidate_metrics.csv")
    cand = [r for r in cand_rows if r["candidate_id"] == cid]
    if len(cand) != 1:
        raise RuntimeError(f"Expected one candidate row for {cid}, found {len(cand)}.")
    cand = cand[0]

    seq_rows = [
        r for r in read_csv_rows(post_dir / "sequence_success_results.csv")
        if r["candidate_id"] == cid
    ]
    target_rows = [
        r for r in read_csv_rows(post_dir / "target_episode_outcomes.csv")
        if r["candidate_id"] == cid
    ]
    nonmoney_rows = [
        r for r in read_csv_rows(post_dir / "nonmoney_episode_outcomes.csv")
        if r["candidate_id"] == cid
    ]
    reset_rows = [
        r for r in read_csv_rows(post_dir / "reset_stage_diagnostics.csv")
        if r["candidate_id"] == cid
    ]
    direct_rows = [
        r for r in read_csv_rows(post_dir / "direct_transition_diagnostics.csv")
        if r["candidate_id"] == cid
    ]

    sequence_failures = [
        {
            "device": r["device"],
            "sequence_id": r["sequence_id"],
            "kind": r["kind"],
            "scenario": r["scenario"],
        }
        for r in seq_rows if not as_bool(r["success"])
    ]

    target_failures = [
        {
            "device": r["device"],
            "sequence_id": r["sequence_id"],
            "scenario": r["scenario"],
            "expected_label": r["expected_label"],
            "outcome": r["outcome"],
        }
        for r in target_rows if r["outcome"] != "correct"
    ]

    nonmoney_false_accepts = [
        {
            "device": r["device"],
            "sequence_id": r["sequence_id"],
            "announced_labels": r["announced_labels"],
        }
        for r in nonmoney_rows if as_bool(r["false_accept"])
    ]

    reset_false_announcements = [
        {
            "device": r["device"],
            "sequence_id": r["sequence_id"],
            "stage_id": r["stage_id"],
            "announced_labels": r["announced_labels"],
        }
        for r in reset_rows if as_bool(r["false_nominal_announcement"])
    ]

    direct_middle_announcements = [
        {
            "device": r["device"],
            "sequence_id": r["sequence_id"],
            "stage_id": r["stage_id"],
            "announcement_count": int(float(r["announcement_count"])),
            "announced_labels": r["announced_labels"],
        }
        for r in direct_rows if float(r["announcement_count"]) > 0
    ]

    # ---------- Final operational configuration ----------
    final_config = {
        "schema_version": 1,
        "status": "operational_configuration_calibrated",
        "revision": "calib-operational-001",
        "analysis_fps": int(selected["analysis_fps"]),
        "threads": int(app_cfg["threads"]),
        "roi_width_fraction": float(selected_static["roi_width_fraction"]),
        "roi_aspect_ratio": float(selected_static["roi_aspect_ratio"]),
        "roi_height_cap_fraction": float(selected_static["roi_height_cap_fraction"]),
        "blur_variance_min": float(selected_static["blur_variance_min"]),
        "luma_min": float(selected_static["luma_min"]),
        "luma_max": float(selected_static["luma_max"]),
        "confidence_threshold": float(selected["confidence_threshold"]),
        "temporal_window_ms": int(selected["temporal_window_ms"]),
        "minimum_results": int(selected["minimum_results"]),
        "clahe_enabled": bool(selected_static["clahe_enabled"]),
        "clahe_clip_limit": None,
        "clahe_grid": None,
        "yuv_range": static_cfg["yuv_range"],
        "log_enabled": bool(app_cfg.get("log_enabled", True)),
    }

    summary = {
        "status": "ready_for_android_operational_lock",
        "selected_configuration": final_config,
        "postinference_evidence": {
            "candidate_id": cid,
            "mssr": float(selected["mssr"]),
            "car": float(selected["car"]),
            "war_nominal_target": float(selected["war"]),
            "rr_nominal": float(selected["rr_nominal"]),
            "nonmoney_false_accept_rate": float(selected["nonmoney_false_accept_rate"]),
            "median_decision_ms": float(selected["median_decision_ms"]),
            "p95_decision_ms": float(selected["p95_decision_ms"]),
            "min_class_car": float(selected["min_class_car"]),
            "eligible_candidate_count": int(decision["quality_gate"]["eligible_candidate_count"]),
            "mssr_one_se_threshold": float(decision["quality_gate"]["mssr_one_se_threshold"]),
        },
        "fps_evidence": seq_audit["fps_selection"],
        "selected_candidate_diagnostics": {
            "sequence_failures": sequence_failures,
            "target_failures": target_failures,
            "nonmoney_false_accepts": nonmoney_false_accepts,
            "reset_false_announcements": reset_false_announcements,
            "direct_transition_middle_announcements": direct_middle_announcements,
            "interpretation": (
                "WAR=0 refers to scored nominal target episodes. "
                "Reset-stage and unlabeled direct-transition announcements remain explicit diagnostics."
            ),
        },
        "dependencies": {
            "static_quality_config_sha256": sha256_file(static_cfg_path),
            "static_quality_lock_sha256": sha256_file(static_lock_path),
            "sequence_input_audit_sha256": sha256_file(seq_audit_path),
            "sequence_input_lock_sha256": actual_seq_lock_sha,
            "postinference_decision_sha256": sha256_file(decision_path),
            "postinference_lock_sha256": sha256_file(post_lock_path),
            "analysis_plan_sha256": seq_lock["analysis_plan_sha256"],
            "android_source_hashes_before_final_patch": actual_android_hashes,
        },
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.validate_only:
        print("\nVALIDATION_STATUS=READY_FOR_OPERATIONAL_LOCK")
        return

    args.out.mkdir(parents=True, exist_ok=True)

    op_cfg_path = args.out / "operational_config.json"
    summary_path = args.out / "operational_selection_summary.json"
    app_final_path = args.out / "android_app_config_final.json"

    write_json(op_cfg_path, final_config)
    write_json(summary_path, summary)

    # Final app_config keeps evidence references but does not modify Android automatically.
    app_final = dict(app_cfg)
    app_final.update({
        "status": "operational_config_locked",
        "revision": "calib-operational-001",
        "analysis_fps": final_config["analysis_fps"],
        "confidence_threshold": final_config["confidence_threshold"],
        "temporal_window_ms": final_config["temporal_window_ms"],
        "minimum_results": final_config["minimum_results"],
        "postinference_status": "calibrated_sequence_locked",
        "note": (
            "Static image-quality and sequence-based post-inference parameters are calibrated and locked. "
            "Use operational_config_lock.json as the research evidence before final Android integration."
        ),
    })
    write_json(app_final_path, app_final)

    lock = {
        "status": "operational_configuration_locked",
        "selected_values": final_config,
        "dependencies": summary["dependencies"],
        "diagnostic_counts": {
            "sequence_failure_count": len(sequence_failures),
            "target_failure_count": len(target_failures),
            "nonmoney_false_accept_count": len(nonmoney_false_accepts),
            "reset_false_announcement_count": len(reset_false_announcements),
            "direct_transition_middle_announcement_count": len(direct_middle_announcements),
        },
        "output_sha256": {
            "operational_config.json": sha256_file(op_cfg_path),
            "operational_selection_summary.json": sha256_file(summary_path),
            "android_app_config_final.json": sha256_file(app_final_path),
        },
    }
    lock_path = args.out / "operational_config_lock.json"
    write_json(lock_path, lock)

    print("\nOPERATIONAL_CONFIG_LOCKED")
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
