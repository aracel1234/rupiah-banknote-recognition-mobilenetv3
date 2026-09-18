import json
from pathlib import Path

import pandas as pd


ROOT = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
MONEY = ROOT / "04_dedup/money_unique_manifest.csv"
NONMONEY = ROOT / "raw_dataset/non_uang"
OUT = ROOT / "05_dataset"

CLASSES = ["1000", "2000", "5000", "10000",
           "20000", "50000", "100000"]
EXT = {".jpg", ".jpeg", ".png", ".webp"}

OUT.mkdir(parents=True, exist_ok=True)

money = pd.read_csv(MONEY, dtype={"label": str})
counts = money["label"].value_counts().reindex(CLASSES)

if counts.isna().any():
    raise RuntimeError("Terdapat kelas uang yang tidak ditemukan.")

files = sorted(
    p for p in NONMONEY.rglob("*")
    if p.is_file() and p.suffix.lower() in EXT
)

target = int(counts.median())
parents = pd.Series(
    [str(p.parent.relative_to(NONMONEY)) for p in files]
).value_counts()

annotations = sorted(
    str(p.relative_to(ROOT))
    for p in (ROOT / "raw_dataset").rglob("instances*.json")
)

summary = {
    "money_samples": int(counts.sum()),
    "money_class_counts": counts.astype(int).to_dict(),
    "money_median": target,
    "money_min": int(counts.min()),
    "money_max": int(counts.max()),
    "money_ir": round(float(counts.max() / counts.min()), 4),
    "nonmoney_available": len(files),
    "nonmoney_target": target,
    "nonmoney_excess": len(files) - target,
    "nonmoney_parent_groups": parents.to_dict(),
    "coco_annotation_candidates": annotations,
    "target_dataset_size": int(counts.sum() + target),
}

(OUT / "stage5a_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print(json.dumps(summary, indent=2, ensure_ascii=False))