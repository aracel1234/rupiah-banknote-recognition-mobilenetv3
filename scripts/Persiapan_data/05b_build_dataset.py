import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
MONEY = ROOT / "04_dedup/money_unique_manifest.csv"
NONMONEY = ROOT / "raw_dataset/non_uang"
OUT = ROOT / "05_dataset"

CLASSES = ["1000", "2000", "5000", "10000",
           "20000", "50000", "100000", "nonuang"]
EXT = {".jpg", ".jpeg", ".png", ".webp"}
SEED = 42

OUT.mkdir(parents=True, exist_ok=True)

# Uang hasil Tahap 4
money = pd.read_csv(MONEY, dtype={"label": str})
money = money[["sample_id", "label", "source_id", "file_path"]].copy()

counts = money["label"].value_counts()
target = int(counts.median())

# Seluruh kandidat nonuang
files = sorted(
    p for p in NONMONEY.iterdir()
    if p.is_file() and p.suffix.lower() in EXT
)

if len(files) < target:
    raise RuntimeError("Jumlah nonuang belum mencapai target.")

# Pemilihan reproducible tanpa replacement
rng = np.random.default_rng(SEED)
chosen = set(rng.choice(len(files), target, replace=False))

nonmoney = pd.DataFrame({
    "sample_id": [f"nm_{p.stem}" for p in files],
    "label": "nonuang",
    "source_id": "ds11",
    "file_path": [str(p.relative_to(ROOT)) for p in files],
    "selected": [i in chosen for i in range(len(files))]
})

if nonmoney["sample_id"].duplicated().any():
    raise RuntimeError("Terdapat sample_id nonuang yang tidak unik.")

selected = nonmoney[nonmoney["selected"]].drop(columns="selected")

# Dataset delapan kelas
dataset = pd.concat([money, selected], ignore_index=True)
dataset["class_index"] = dataset["label"].map(
    {name: i for i, name in enumerate(CLASSES)}
)

if dataset["class_index"].isna().any():
    raise RuntimeError("Terdapat label yang tidak dikenal.")

if dataset["sample_id"].duplicated().any():
    raise RuntimeError("Terdapat sample_id ganda.")

dataset = dataset.sort_values(["class_index", "sample_id"])

final_counts = (
    dataset["label"]
    .value_counts()
    .reindex(CLASSES)
    .astype(int)
)

nonmoney.to_csv(OUT / "nonmoney_selection.csv", index=False)
dataset.to_csv(OUT / "dataset_manifest.csv", index=False)

summary = {
    "seed": SEED,
    "money_samples": len(money),
    "nonmoney_available": len(files),
    "nonmoney_selected": len(selected),
    "nonmoney_not_selected": len(files) - len(selected),
    "dataset_total": len(dataset),
    "class_counts": final_counts.to_dict(),
    "imbalance_ratio": round(
        float(final_counts.max() / final_counts.min()), 4
    ),
    "ready_for_split": len(dataset) == len(money) + target
}

(OUT / "stage5b_summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print(json.dumps(summary, indent=2, ensure_ascii=False))