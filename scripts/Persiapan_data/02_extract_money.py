import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import cv2
from tqdm import tqdm

DATA = Path("/home/aracel/Downloads/Skripsi/persiapan_data")

IMAGE_DIR = DATA / "raw_dataset/uang/all_image"
JSON_FILE = DATA / "raw_dataset/uang/all_data_merged.json"
OUT_DIR = DATA / "02_extracted"
CROP_DIR = OUT_DIR / "uang"

CLASS_MAP = {
    "seribu": "1000",
    "dua ribu": "2000",
    "lima ribu": "5000",
    "sepuluh ribu": "10000",
    "dua puluh ribu": "20000",
    "lima puluh ribu": "50000",
    "seratus ribu": "100000",
}

for label in CLASS_MAP.values():
    (CROP_DIR / label).mkdir(parents=True, exist_ok=True)

with open(JSON_FILE, encoding="utf-8") as f:
    coco = json.load(f)

images = {img["id"]: img for img in coco["images"]}
categories = {c["id"]: c["name"] for c in coco["categories"]}

ann_by_image = defaultdict(list)
for ann in coco["annotations"]:
    ann_by_image[ann["image_id"]].append(ann)

excluded = []
issues = []
class_count = Counter()

saved = 0
clipped = 0

for image_id, info in tqdm(images.items(), desc="Ekstraksi uang"):
    annotations = ann_by_image.get(image_id, [])

    if not annotations:
        excluded.append([image_id, info["file_name"], "no_annotation"])
        continue

    image = cv2.imread(str(IMAGE_DIR / info["file_name"]))

    if image is None:
        issues.append([
            image_id, "", info["file_name"],
            "image_read_failed"
        ])
        continue

    height, width = image.shape[:2]

    if width != info["width"] or height != info["height"]:
        issues.append([
            image_id, "", info["file_name"],
            f"dimension_mismatch: actual={width}x{height}, "
            f"json={info['width']}x{info['height']}"
        ])
        continue

    source_id = info["file_name"].split("_", 1)[0]

    for ann in annotations:
        label_name = categories.get(ann["category_id"])
        label = CLASS_MAP.get(label_name)

        if label is None:
            issues.append([
                image_id, ann["id"], info["file_name"],
                f"unknown_class: {label_name}"
            ])
            continue

        x, y, w, h = ann["bbox"]

        raw_x1 = math.floor(x)
        raw_y1 = math.floor(y)
        raw_x2 = math.ceil(x + w)
        raw_y2 = math.ceil(y + h)

        x1 = max(0, raw_x1)
        y1 = max(0, raw_y1)
        x2 = min(width, raw_x2)
        y2 = min(height, raw_y2)

        if (
            x1 != raw_x1 or y1 != raw_y1 or
            x2 != raw_x2 or y2 != raw_y2
        ):
            clipped += 1

        if x2 <= x1 or y2 <= y1:
            issues.append([
                image_id, ann["id"], info["file_name"],
                "invalid_crop_after_clipping"
            ])
            continue

        crop = image[y1:y2, x1:x2]

        output_name = (
            f"{source_id}_img{image_id:06d}_"
            f"ann{ann['id']:06d}.png"
        )

        output_path = CROP_DIR / label / output_name

        if not cv2.imwrite(
            str(output_path),
            crop,
            [cv2.IMWRITE_PNG_COMPRESSION, 0]
        ):

            issues.append([
                image_id, ann["id"], info["file_name"],
                "image_write_failed"
            ])
            continue

        class_count[label] += 1
        saved += 1


with open(
    OUT_DIR / "excluded_no_annotation.csv",
    "w",
    newline="",
    encoding="utf-8"
) as f:
    writer = csv.writer(f)
    writer.writerow(["image_id", "file_name", "reason"])
    writer.writerows(excluded)


with open(
    OUT_DIR / "extraction_issues.csv",
    "w",
    newline="",
    encoding="utf-8"
) as f:
    writer = csv.writer(f)
    writer.writerow([
        "image_id", "annotation_id", "file_name", "issue"
    ])
    writer.writerows(issues)


summary = {
    "source_images": len(images),
    "source_annotations": len(coco["annotations"]),
    "excluded_no_annotation": len(excluded),
    "bbox_clipped": clipped,
    "crops_saved": saved,
    "issues": len(issues),
    "output_format": "PNG",
    "resize_applied": False,
    "class_counts": dict(sorted(class_count.items())),
}

with open(
    OUT_DIR / "extraction_summary.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(json.dumps(summary, indent=2, ensure_ascii=False))