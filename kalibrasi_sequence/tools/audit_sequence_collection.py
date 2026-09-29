#!/usr/bin/env python3
import argparse, csv, hashlib, json, math, sys
from pathlib import Path

EXPECTED_MODEL = "fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676"
REQUIRED_FRAME_COLUMNS = [
    "frame_index","elapsed_ms","stage_id","expected_label","analysis_role","quality_pass","quality_code",
    "score_1000","score_2000","score_5000","score_10000","score_20000","score_50000","score_100000","score_nonuang",
    "top_label","top_score","pipeline_ms"
]
SCORE_COLUMNS = ["score_1000","score_2000","score_5000","score_10000","score_20000","score_50000","score_100000","score_nonuang"]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def find_sequence_dirs(root: Path):
    seq_root = root / "sequences"
    if not seq_root.exists():
        return []
    return sorted({p.parent for p in seq_root.rglob("metadata.json")})

def audit(root: Path, require_complete=False):
    errors, warnings = [], []
    stats = {"root": str(root), "sequences": 0, "frames": 0, "inference_frames": 0}
    required_root = ["experiment_plan.json", "checklist.json", "checklist.csv", "manifest.jsonl", "manifest.csv", "collector_config.json"]
    for name in required_root:
        if not (root / name).exists():
            errors.append(f"missing root file: {name}")

    checklist = []
    if (root / "checklist.json").exists():
        checklist = json.loads((root / "checklist.json").read_text())
        ids = [x["id"] for x in checklist]
        if len(checklist) != 40: errors.append(f"checklist count {len(checklist)} != 40")
        if len(set(ids)) != len(ids): errors.append("duplicate sequence_id in checklist")
        counts = {}
        for x in checklist: counts[x["kind"]] = counts.get(x["kind"], 0) + 1
        for kind, expected in {"NOMINAL":28, "NONUANG":6, "TRANSITION":6}.items():
            if counts.get(kind, 0) != expected: errors.append(f"{kind} count {counts.get(kind,0)} != {expected}")
        saved = sum(1 for x in checklist if x.get("status") == "SAVED")
        stats["saved_checklist"] = saved
        if require_complete and saved != 40: errors.append(f"collection incomplete: {saved}/40 saved")

    config_hash = None
    if (root / "collector_config.json").exists():
        cfg = json.loads((root / "collector_config.json").read_text())
        config_hash = cfg.get("config_sha256")
        if cfg.get("status") != "confirmed_for_sequence_collection":
            errors.append("collector_config is not confirmed_for_sequence_collection")

    seq_dirs = find_sequence_dirs(root)
    stats["sequences"] = len(seq_dirs)
    metadata_ids = set()
    for d in seq_dirs:
        for name in ["frames.csv", "stages.json", "metadata.json", "config_snapshot.json"]:
            if not (d / name).exists(): errors.append(f"{d}: missing {name}")
        if not (d / "metadata.json").exists() or not (d / "frames.csv").exists():
            continue
        m = json.loads((d / "metadata.json").read_text())
        sid = m.get("sequence_id")
        if sid in metadata_ids: errors.append(f"duplicate metadata sequence_id: {sid}")
        metadata_ids.add(sid)
        if m.get("model_sha256") != EXPECTED_MODEL:
            errors.append(f"{sid}: unexpected model hash {m.get('model_sha256')}")
        if config_hash and m.get("config_sha256") != config_hash:
            errors.append(f"{sid}: config hash differs from collector_config")
        for name, key in [("frames.csv","frames_csv_sha256"),("stages.json","stages_json_sha256"),("config_snapshot.json","config_snapshot_sha256")]:
            p = d / name
            if p.exists() and m.get(key) and sha256(p) != m.get(key):
                errors.append(f"{sid}: SHA mismatch for {name}")

        with (d / "frames.csv").open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                errors.append(f"{sid}: frames.csv has no header")
                continue
            missing = [c for c in REQUIRED_FRAME_COLUMNS if c not in reader.fieldnames]
            if missing: errors.append(f"{sid}: missing frame columns {missing}")
            rows = list(reader)
        stats["frames"] += len(rows)
        if int(m.get("sampled_frames", -1)) != len(rows):
            errors.append(f"{sid}: metadata sampled_frames != CSV rows")
        last_elapsed = -1
        inferred = 0
        for i, r in enumerate(rows, 1):
            try: elapsed = int(r["elapsed_ms"])
            except Exception:
                errors.append(f"{sid}: bad elapsed_ms row {i}"); continue
            if elapsed < last_elapsed: errors.append(f"{sid}: non-monotonic elapsed_ms row {i}")
            last_elapsed = elapsed
            quality = r.get("quality_pass", "").lower() == "true"
            vals = [r.get(c, "") for c in SCORE_COLUMNS]
            if quality:
                if any(v == "" for v in vals):
                    errors.append(f"{sid}: quality-pass row {i} has missing scores")
                    continue
                try: scores = [float(v) for v in vals]
                except Exception:
                    errors.append(f"{sid}: invalid score row {i}"); continue
                if not all(math.isfinite(x) and -0.001 <= x <= 1.001 for x in scores):
                    errors.append(f"{sid}: out-of-range score row {i}")
                if abs(sum(scores) - 1.0) >= 0.01:
                    errors.append(f"{sid}: score sum not ~1 row {i}: {sum(scores):.6f}")
                inferred += 1
            else:
                if any(v != "" for v in vals): warnings.append(f"{sid}: rejected row {i} still has scores")
        stats["inference_frames"] += inferred
        if int(m.get("inference_frames", -1)) != inferred:
            errors.append(f"{sid}: metadata inference_frames != score rows")
        if len(rows) < 20:
            warnings.append(f"{sid}: only {len(rows)} sampled frames; inspect device throughput")
        if float(m.get("achieved_sample_fps", 0.0)) < 4.0:
            warnings.append(f"{sid}: achieved sample FPS < 4.0 ({m.get('achieved_sample_fps')})")
        if float(m.get("p95_pipeline_ms", 999999)) > 200.0:
            warnings.append(f"{sid}: p95 pipeline > 200 ms; 5 FPS may not be sustainable")

    checklist_saved_ids = {x["id"] for x in checklist if x.get("status") == "SAVED"}
    if checklist_saved_ids != metadata_ids:
        missing = sorted(checklist_saved_ids - metadata_ids)
        extra = sorted(metadata_ids - checklist_saved_ids)
        if missing: errors.append(f"saved checklist entries without metadata: {missing}")
        if extra: errors.append(f"metadata exists but checklist not SAVED: {extra}")

    result = {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}
    (root / "audit_report.json").write_text(json.dumps(result, indent=2))
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="Device dataset root, e.g. .../RupiahSequenceCollector/poco_x5_pro_5g")
    ap.add_argument("--require-complete", action="store_true")
    args = ap.parse_args()
    result = audit(args.root, args.require_complete)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 2)

if __name__ == "__main__": main()
