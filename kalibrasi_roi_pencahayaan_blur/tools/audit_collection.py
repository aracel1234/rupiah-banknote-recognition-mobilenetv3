#!/usr/bin/env python3
import csv, hashlib, json, sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 tools/audit_collection.py /path/to/device_alias_folder")
root = Path(sys.argv[1])
checklist = root / "checklist.csv"
manifest = root / "manifest.csv"
if not checklist.exists():
    raise SystemExit(f"Missing {checklist}")

with checklist.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
print(f"checklist rows: {len(rows)} (expected 360)")
quality = [r for r in rows if r["group"] == "quality"]
roi = [r for r in rows if r["group"] == "roi"]
print(f"quality: {len(quality)} (expected 240); saved={sum(r['status']=='SAVED' for r in quality)}")
print(f"roi: {len(roi)} (expected 120); saved={sum(r['status']=='SAVED' for r in roi)}")

missing = []
hash_errors = []
if manifest.exists():
    with manifest.open(newline="", encoding="utf-8") as f:
        mrows = list(csv.DictReader(f))
    print(f"manifest accepted samples: {len(mrows)}")
    for r in mrows:
        for path_key, hash_key in [("relative_rgb_path", "rgb_sha256"), ("relative_luma_path", "luma_sha256")]:
            p = root / r[path_key]
            if not p.exists():
                missing.append(str(p))
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            if h != r[hash_key]:
                hash_errors.append(str(p))
else:
    print("manifest.csv not found")

print(f"missing files: {len(missing)}")
print(f"hash mismatches: {len(hash_errors)}")
if missing:
    print("\nMissing:")
    print("\n".join(missing[:20]))
if hash_errors:
    print("\nHash mismatch:")
    print("\n".join(hash_errors[:20]))

complete = len(rows) == 360 and all(r["status"] == "SAVED" for r in rows) and not missing and not hash_errors
print("DATASET_STATUS=" + ("COMPLETE" if complete else "INCOMPLETE"))
