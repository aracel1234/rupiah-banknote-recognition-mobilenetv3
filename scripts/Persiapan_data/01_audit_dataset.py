import json
import re
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path("/home/aracel/Downloads/Skripsi/persiapan_data")

MONEY_DIR = DATA / "raw_dataset/uang/all_image"
JSON_FILE = DATA / "raw_dataset/uang/all_data_merged.json"
NONMONEY_DIR = DATA / "raw_dataset/non_uang"
OUT_DIR = DATA / "01_audit"

OUT_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

with open(JSON_FILE, encoding="utf-8") as f:
    coco = json.load(f)

images = {img["id"]: img for img in coco["images"]}
categories = {c["id"]: c["name"] for c in coco["categories"]}

ann_by_image = defaultdict(list)
for ann in coco["annotations"]:
    ann_by_image[ann["image_id"]].append(ann)

money_files = {
    p.name for p in MONEY_DIR.iterdir()
    if p.is_file() and p.suffix.lower() in IMAGE_EXT
}

nonmoney_files = [
    p for p in NONMONEY_DIR.rglob("*")
    if p.is_file() and p.suffix.lower() in IMAGE_EXT
]

source_count = Counter()
class_count = Counter()
bbox_invalid = 0
bbox_outside = 0
annotation_without_image = 0

for img in images.values():
    match = re.match(r"^(ds\d+)_", img["file_name"])
    source_count[match.group(1) if match else "unknown"] += 1

for ann in coco["annotations"]:
    img = images.get(ann["image_id"])

    if img is None:
        annotation_without_image += 1
        continue

    class_count[categories.get(ann["category_id"], "unknown")] += 1

    x, y, w, h = ann["bbox"]

    if w <= 0 or h <= 0:
        bbox_invalid += 1

    if (
        x < 0 or y < 0 or
        x + w > img["width"] or
        y + h > img["height"]
    ):
        bbox_outside += 1

json_files = {img["file_name"] for img in images.values()}

summary = {
    "money_images_json": len(images),
    "money_files_disk": len(money_files),
    "annotations": len(coco["annotations"]),
    "nonmoney_files_disk": len(nonmoney_files),

    "missing_money_files": len(json_files - money_files),
    "money_files_not_in_json": len(money_files - json_files),

    "images_without_annotation":
        sum(len(ann_by_image[i]) == 0 for i in images),

    "images_one_annotation":
        sum(len(ann_by_image[i]) == 1 for i in images),

    "images_multiple_annotations":
        sum(len(ann_by_image[i]) > 1 for i in images),

    "annotation_without_image": annotation_without_image,
    "bbox_invalid_size": bbox_invalid,
    "bbox_outside_image": bbox_outside,

    "source_counts": dict(sorted(source_count.items())),
    "class_counts": dict(sorted(class_count.items())),
}

with open(OUT_DIR / "audit_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(json.dumps(summary, indent=2, ensure_ascii=False))