import json
import math
from pathlib import Path

import pandas as pd


DATA = Path("/home/aracel/Downloads/Skripsi/persiapan_data")

JSON_FILE = DATA / "raw_dataset/uang/all_data_merged.json"
CROP_DIR = DATA / "02_extracted/uang"
OUT_DIR = DATA / "03_curated"

AUDIT_RATE = 0.05
MIN_AUDIT = 50
SEED = 42

CLASS_MAP = {
    "seribu": "1000",
    "dua ribu": "2000",
    "lima ribu": "5000",
    "sepuluh ribu": "10000",
    "dua puluh ribu": "20000",
    "lima puluh ribu": "50000",
    "seratus ribu": "100000",
}

OUT_DIR.mkdir(parents=True, exist_ok=True)

with open(JSON_FILE, encoding="utf-8") as f:
    coco = json.load(f)

images = {img["id"]: img for img in coco["images"]}
categories = {
    c["id"]: c["name"].strip().lower()
    for c in coco["categories"]
}

rows = []

for ann in coco["annotations"]:
    img = images[ann["image_id"]]
    label = CLASS_MAP[categories[ann["category_id"]]]

    x, y, w, h = ann["bbox"]

    rx1 = math.floor(x)
    ry1 = math.floor(y)
    rx2 = math.ceil(x + w)
    ry2 = math.ceil(y + h)

    x1 = max(0, rx1)
    y1 = max(0, ry1)
    x2 = min(img["width"], rx2)
    y2 = min(img["height"], ry2)

    crop_w = x2 - x1
    crop_h = y2 - y1

    raw_area = (rx2 - rx1) * (ry2 - ry1)
    crop_area = crop_w * crop_h

    source = img["file_name"].split("_", 1)[0]

    file_name = (
        f"{source}_img{img['id']:06d}_"
        f"ann{ann['id']:06d}.png"
    )

    path = CROP_DIR / label / file_name

    rows.append({
        "sample_id": Path(file_name).stem,
        "label": label,
        "source_id": source,
        "image_id": img["id"],
        "annotation_id": ann["id"],
        "file_path": str(path.relative_to(DATA)),
        "r_clip": crop_area / raw_area,
        "aspect_ratio": crop_w / crop_h,
        "relative_area": crop_area / (
            img["width"] * img["height"]
        ),
        "file_exists": path.is_file(),
    })

df = pd.DataFrame(rows)

df["flag_clip"] = df["r_clip"] < 0.90
df["flag_aspect"] = False
df["flag_area"] = False
df["random_5pct"] = False

bounds = {}

for label, group in df.groupby("label"):
    bounds[label] = {}

    for column, flag in [
        ("aspect_ratio", "flag_aspect"),
        ("relative_area", "flag_area"),
    ]:
        q1 = group[column].quantile(0.25)
        q3 = group[column].quantile(0.75)
        iqr = q3 - q1

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        df.loc[group.index, flag] = (
            (group[column] < lower) |
            (group[column] > upper)
        )

        bounds[label][column] = {
            "lower": float(lower),
            "upper": float(upper),
        }

    n = max(
        MIN_AUDIT,
        math.ceil(len(group) * AUDIT_RATE)
    )

    selected = group.sample(
        n=n,
        random_state=SEED
    ).index

    df.loc[selected, "random_5pct"] = True


df["auto_flag"] = (
    ~df["file_exists"] |
    df["flag_clip"] |
    df["flag_aspect"] |
    df["flag_area"]
)

df["audit_required"] = (
    df["auto_flag"] |
    df["random_5pct"]
)


def audit_reason(row):
    reasons = []

    if not row["file_exists"]:
        reasons.append("missing_file")
    if row["flag_clip"]:
        reasons.append("clip")
    if row["flag_aspect"]:
        reasons.append("aspect_outlier")
    if row["flag_area"]:
        reasons.append("area_outlier")
    if row["random_5pct"]:
        reasons.append("random_5pct")

    return ";".join(reasons)


audit = df[df["audit_required"]].copy()
audit["audit_reason"] = audit.apply(audit_reason, axis=1)
audit["decision"] = ""
audit["notes"] = ""

audit.to_csv(
    OUT_DIR / "visual_audit.csv",
    index=False
)

class_summary = {}

for label, group in df.groupby("label"):
    audit_group = group[group["audit_required"]]

    class_summary[label] = {
        "samples": len(group),
        "random_5pct": int(group["random_5pct"].sum()),
        "auto_flagged": int(group["auto_flag"].sum()),
        "audit_total": len(audit_group),
    }

summary = {
    "total_samples": len(df),
    "missing_files": int((~df["file_exists"]).sum()),
    "flag_clip": int(df["flag_clip"].sum()),
    "flag_aspect": int(df["flag_aspect"].sum()),
    "flag_area": int(df["flag_area"].sum()),
    "auto_flagged": int(df["auto_flag"].sum()),
    "random_5pct": int(df["random_5pct"].sum()),
    "visual_audit_total": len(audit),
    "seed": SEED,
    "class_summary": class_summary,
    "iqr_bounds": bounds,
}

with open(
    OUT_DIR / "curation_summary.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(json.dumps(summary, indent=2, ensure_ascii=False))