import hashlib, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import pandas as pd
from tqdm import tqdm

ROOT = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
CROPS = ROOT / "02_extracted/uang"
AUDIT = ROOT / "03_curated/visual_audit_reviewed.csv"
OUT = ROOT / "04_dedup"

CLASSES = ["1000", "2000", "5000", "10000", "20000", "50000", "100000"]
WORKERS = 4

OUT.mkdir(parents=True, exist_ok=True)
cv2.setNumThreads(1)

audit = pd.read_csv(AUDIT, dtype=str).fillna("")
if audit["sample_id"].duplicated().any():
    raise RuntimeError("Terdapat sample_id ganda pada audit visual.")

decision = audit["decision"].str.strip().str.lower()
invalid = sorted(set(decision) - {"valid", "exclude"})
if invalid:
    raise RuntimeError(f"Keputusan audit belum valid: {invalid}")

excluded = set(audit.loc[decision.eq("exclude"), "sample_id"])

all_files = sorted(CROPS.glob("*/*.png"))
all_ids = {p.stem for p in all_files}

missing = excluded - all_ids
if missing:
    raise RuntimeError(f"{len(missing)} sampel exclude tidak ditemukan.")

files = [p for p in all_files if p.stem not in excluded]

def hash_image(p):
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        return None

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    sha = hashlib.sha256(
        f"{h}x{w}|RGB|".encode() + rgb.tobytes()
    ).hexdigest()

    sid = p.stem
    return {
        "sample_id": sid,
        "label": p.parent.name,
        "source_id": sid.split("_", 1)[0],
        "file_path": str(p.relative_to(ROOT)),
        "sha256": sha,
    }

with ThreadPoolExecutor(max_workers=WORKERS) as executor:
    rows = list(tqdm(
        executor.map(hash_image, files),
        total=len(files),
        desc="SHA-256"
    ))

if any(r is None for r in rows):
    raise RuntimeError("Ada citra yang gagal dibaca.")

df = pd.DataFrame(rows)

bad_labels = sorted(set(df["label"]) - set(CLASSES))
if bad_labels:
    raise RuntimeError(f"Label tidak dikenal: {bad_labels}")

df["status"] = "keep"
df["keep_sample_id"] = df["sample_id"]

for _, group in df.groupby("sha256", sort=False):
    if len(group) == 1:
        continue

    if group["label"].nunique() > 1:
        df.loc[group.index, "status"] = "exact_conflict"
        df.loc[group.index, "keep_sample_id"] = ""
        continue

    keeper = group["sample_id"].min()
    dup_idx = group.index[group["sample_id"].ne(keeper)]

    df.loc[dup_idx, "status"] = "exact_duplicate"
    df.loc[dup_idx, "keep_sample_id"] = keeper

df = df.sort_values(["label", "sample_id"])

keep = df[df["status"].eq("keep")]
dup = df[df["status"].eq("exact_duplicate")]
conflict = df[df["status"].eq("exact_conflict")]

# Artefak keterlacakan
df.to_csv(OUT / "dedup_manifest.csv", index=False)
keep.to_csv(OUT / "money_unique_manifest.csv", index=False)

dup[
    ["sample_id", "keep_sample_id", "label", "source_id", "sha256"]
].to_csv(OUT / "exact_duplicates.csv", index=False)

conflict[
    ["sha256", "sample_id", "label", "source_id"]
].to_csv(OUT / "exact_conflicts.csv", index=False)

summary = {
    "stage2_crops": len(all_files),
    "excluded_visual_audit": len(excluded),
    "dedup_candidates": len(df),
    "exact_duplicate_groups": int(dup["sha256"].nunique()),
    "exact_duplicates_removed": len(dup),
    "exact_conflict_groups": int(conflict["sha256"].nunique()),
    "exact_conflict_samples": len(conflict),
    "kept_samples": len(keep),
    "ready_for_next_stage": len(conflict) == 0,
    "class_before_dedup": (
        df["label"].value_counts()
        .reindex(CLASSES, fill_value=0)
        .to_dict()
    ),
    "class_after_dedup": (
        keep["label"].value_counts()
        .reindex(CLASSES, fill_value=0)
        .to_dict()
    ),
}

(OUT / "dedup_summary.json").write_text(
    json.dumps(summary, indent=2),
    encoding="utf-8"
)

print(json.dumps(summary, indent=2))