"""Inventarisasi kelas dan merge COCO; identitas keluaran mengikuti arsip lama."""
import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

GROUPS = {
    "seribu": ("1-rb", "1000", "1k", "1ribu", "seribu"),
    "dua ribu": ("2000", "2k", "2ribu", "dua ribu"),
    "lima ribu": ("5000", "5k", "5ribu", "lima ribu"),
    "sepuluh ribu": ("10000", "10k", "10ribu", "sepuluh ribu"),
    "dua puluh ribu": ("20000", "20k", "20rb", "20ribu", "dua puluh ribu"),
    "lima puluh ribu": ("50000", "50k", "50ribu", "lima puluh ribu"),
    "seratus ribu": ("100000", "100k", "100ribu", "seratus ribu"),
}
CATEGORIES = [{"id": i, "name": name} for i, name in enumerate(GROUPS, 1)]
MAPPING = {alias: i for i, aliases in enumerate(GROUPS.values(), 1) for alias in aliases}
SPLITS = ("train", "valid", "test")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def inventory(raw):
    if not raw.is_dir():
        raise ValueError(f"Folder sumber tidak ditemukan: {raw}")
    records, missing = [], []
    for source in sorted(f"ds{i}" for i in range(1, 11)):
        folder = raw / f"ds{int(source[2:]):02d}"
        if not folder.is_dir():
            raise ValueError(f"Folder wajib tidak ditemukan: {folder}")
        for split in SPLITS:
            path = folder / split / "_annotations.coco.json"
            if not path.is_file():
                missing.append(str(path))
                continue
            data = load(path)
            for key in ("images", "annotations", "categories"):
                if not isinstance(data.get(key), list):
                    raise ValueError(f"{path}: {key} harus berupa list")
            for key in ("images", "categories"):
                ids = [item["id"] for item in data[key]]
                if len(ids) != len(set(ids)):
                    raise ValueError(f"{path}: ID {key} tidak unik")
            records.append((source, split, path, data))
    if not records:
        raise ValueError("Tidak ada JSON COCO yang ditemukan")
    return records, missing


def merge(records, output, missing, reference=None):
    if output.exists():
        raise ValueError(f"Keluaran sudah ada: {output}. Pilih folder baru dengan --output.")
    output.mkdir(parents=True)
    image_dir = output / "all_images"
    image_dir.mkdir()
    images, annotations, issues, names = [], [], [], set()
    sources = {}
    for source, split, path, data in records:
        stats = sources.setdefault(source, Counter())
        categories = {c["id"]: MAPPING.get(c["name"]) for c in data["categories"]}
        id_map = {}
        for item in data["images"]:
            stats["input_images"] += 1
            filename = item["file_name"]
            relative = Path(filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Nama berkas tidak aman: {filename}")
            source_path = path.parent / relative
            if not source_path.exists():
                source_path = path.parent / "image" / relative
            if not source_path.is_file():
                stats["missing_images"] += 1
                issues.append({"type": "missing_image", "source": source, "split": split,
                               "image_id": item["id"], "file_name": filename})
                continue
            new_name = f"{source}_{split}_{filename}"
            if new_name in names:
                raise ValueError(f"Nama keluaran bertabrakan: {new_name}")
            destination = image_dir / new_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source_path, destination)
            names.add(new_name)
            new_id = len(images) + 1
            id_map[item["id"]] = new_id
            images.append({**item, "id": new_id, "file_name": new_name})
            stats["copied_images"] += 1
        for item in data["annotations"]:
            stats["input_annotations"] += 1
            category = categories.get(item["category_id"])
            reasons = []
            if category is None:
                reasons.append("unmapped_category")
            if item["image_id"] not in id_map:
                reasons.append("image_not_copied")
            if reasons:
                stats["skipped_annotations"] += 1
                issues.append({"type": "skipped_annotation", "source": source, "split": split,
                               "annotation_id": item["id"], "category_id": item["category_id"],
                               "image_id": item["image_id"], "reasons": reasons})
                continue
            annotations.append({**item, "id": len(annotations) + 1,
                                "image_id": id_map[item["image_id"]], "category_id": category})
            stats["kept_annotations"] += 1
    result = {"images": images, "annotations": annotations, "categories": CATEGORIES}
    count = Counter(a["image_id"] for a in annotations)
    report = {"images": len(images), "annotations": len(annotations),
              "images_without_annotation": sum(not count[i["id"]] for i in images),
              "image_count_matches_historical_40344": len(images) == 40344,
              "annotation_count_matches_historical_40062": len(annotations) == 40062,
              "sources": sources, "missing_json": missing, "issues": issues,
              "reference_comparison": None,
              "note": "Kesamaan metadata tidak membuktikan kesamaan piksel gambar."}
    if reference is not None:
        old = load(reference)
        report["reference_comparison"] = {
            key: result[key] == old.get(key) for key in result
        }
    (output / "all_data_merged.json").write_text(json.dumps(result), encoding="utf-8")
    (output / "merge_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Tersimpan: {len(images)} gambar; {len(annotations)} anotasi; "
          f"{report['images_without_annotation']} gambar tanpa anotasi.")
    print(f"Laporan: {output / 'merge_report.json'}")
    comparison = report["reference_comparison"]
    if comparison is not None:
        print("Perbandingan metadata terhadap referensi:", comparison)
        if not all(comparison.values()):
            print("BERBEDA: jangan mengganti masukan tahap 01 dan seterusnya.")
            return 2
    if len(images) != 40344 or len(annotations) != 40062:
        print("PERHATIAN: jumlah berbeda dari arsip; jangan anggap hasil identik.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("/home/aracel/Downloads/Skripsi/raw_data"))
    parser.add_argument("--output", type=Path, default=Path("/home/aracel/Downloads/Skripsi/merge_dataset"))
    parser.add_argument("--reference", type=Path, help="JSON historis untuk pembandingan metadata lengkap")
    parser.add_argument("--merge", action="store_true", help="Salin gambar dan tulis JSON setelah inventarisasi")
    args = parser.parse_args()
    if args.reference is not None and not args.reference.is_file():
        parser.error(f"JSON referensi tidak ditemukan: {args.reference}")
    try:
        records, missing = inventory(args.raw)
        for source in sorted({r[0] for r in records}):
            names = {c["name"] for s, _, _, d in records if s == source for c in d["categories"]}
            print(f"\n{source} (folder ds{int(source[2:]):02d})")
            for name in sorted(names, key=lambda x: json.dumps(x, ensure_ascii=False)):
                target = MAPPING.get(name)
                label = CATEGORIES[target - 1]["name"] if target is not None else "TIDAK DIPETAKAN"
                print(f"  {name!r} -> {label}")
        for path in missing:
            print(f"JSON tidak tersedia, dilewati: {path}")
        if not args.merge:
            print("\nTinjau GROUPS, lalu jalankan kembali dengan --merge. Belum ada gambar disalin.")
            return 0
        return merge(records, args.output, missing, args.reference)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Gagal: {error}\nKeluaran parsial, jika ada, tidak boleh dipakai untuk tahap lanjutan.\n")


if __name__ == "__main__":
    raise SystemExit(main())
