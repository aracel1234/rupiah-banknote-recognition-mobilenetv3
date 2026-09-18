"""Bagian 1: integritas manifest, RGB bilinear, dan augmentasi data latih."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

CLASSES = ["1000", "2000", "5000", "10000", "20000", "50000", "100000", "nonuang"]
DEFAULT_ROOT = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
IMAGE_SHAPE = (224, 224, 3)


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_inputs(root):
    root = Path(root)
    folder = root / "05_dataset"
    read = lambda path: pd.read_csv(path, dtype={"label": str})
    labels = json.loads((root / "01_audit/class_names.json").read_text())
    require(labels == CLASSES, "Urutan kelas berubah.")
    summary = json.loads((folder / "stage5c_summary.json").read_text())
    for name in ("split", "test"):
        require(sha256(folder / f"{name}_manifest.csv") ==
                summary[f"{name}_manifest_sha256"], f"Hash manifest {name} berubah.")
    full = read(folder / "split_manifest.csv")
    require(not full.isna().any().any(), "Manifest memuat nilai kosong.")
    require(len(full) == summary["dataset_total"], "Jumlah dataset tidak sesuai.")
    for column in ("sample_id", "file_path"):
        require(full[column].is_unique, f"Terdapat {column} ganda.")
    require(set(full["split"]) == {"train", "validation", "test"}, "Partisi tidak valid.")
    require(full["class_index"].eq(full["label"].map(dict(zip(CLASSES, range(8))))).all(),
            "Label dan class_index tidak sesuai.")
    original = read(folder / "dataset_manifest.csv")
    canonical = lambda df: df.sort_values("sample_id").reset_index(drop=True)
    require(canonical(full.drop(columns="split")).equals(canonical(original)),
            "Dataset dan split tidak memuat sampel yang sama.")
    parts = {}
    for name in ("train", "validation", "test"):
        part = read(folder / f"{name}_manifest.csv")
        require(part.equals(full[full["split"].eq(name)].reset_index(drop=True)),
                f"Isi/urutan manifest {name} berbeda dari split_manifest.")
        counts = part["label"].value_counts().to_dict()
        require(counts == summary["class_counts"][name], f"Distribusi {name} berubah.")
        require(set(counts) == set(CLASSES), f"Kelas {name} tidak lengkap.")
        parts[name] = part
    money = read(root / "04_dedup/money_unique_manifest.csv")
    require(money["sha256"].notna().all() and money["sha256"].is_unique,
            "Hash uang kosong atau tidak unik.")
    require(set(money["sample_id"]) == set(full.loc[full["label"].ne("nonuang"), "sample_id"]),
            "Sampel uang berbeda dari hasil deduplikasi.")
    weights = {int(k): float(v) for k, v in
               json.loads((folder / "class_weights.json").read_text()).items()}
    counts = parts["train"]["class_index"].value_counts().reindex(range(8))
    require(set(weights) == set(range(8)), "Indeks class weight tidak lengkap.")
    require(np.allclose([weights[i] for i in range(8)], len(parts["train"]) / (8 * counts),
                        rtol=0, atol=1e-8), "Class weight tidak sesuai data latih.")
    money_split = full[full["label"].ne("nonuang")].copy()
    money_split["parent_id"] = money_split["sample_id"].str.replace(r"_ann\d+$", "", regex=True)
    groups = money_split.groupby("parent_id")["split"].nunique()
    related = money_split[money_split["parent_id"].isin(groups[groups.gt(1)].index)]
    report = {"metadata_valid": True, "split_counts": {k: len(v) for k, v in parts.items()},
              "manifest_sha256": {k: sha256(folder / f"{k}_manifest.csv") for k in parts},
              "parent_groups_cross_split": int(groups.gt(1).sum()),
              "related_samples_cross_split": len(related), "image_content_checked": False}
    return parts, weights, report, related


def configure_runtime(seed):
    import tensorflow as tf
    tf.keras.backend.set_image_data_format("channels_last")
    tf.keras.mixed_precision.set_global_policy("float32")
    tf.keras.utils.set_random_seed(seed)
    tf.config.experimental.enable_op_determinism()
    return tf


def make_dataset(root, frame, batch_size=16, training=False, seed=42):
    import tensorflow as tf
    require(batch_size > 0, "Batch size harus positif.")
    paths = [str(Path(root) / p) for p in frame["file_path"]]
    missing = [p for p in paths if not Path(p).is_file()]
    require(not missing, f"{len(missing)} citra tidak ditemukan; contoh: {missing[:1]}")
    ds = tf.data.Dataset.from_tensor_slices((paths, frame["class_index"].to_numpy(np.int32)))
    if training:
        ds = ds.shuffle(len(frame), seed=seed, reshuffle_each_iteration=True)

    def decode(path, label):
        image = tf.io.decode_image(tf.io.read_file(path), channels=3, expand_animations=False)
        image.set_shape((None, None, 3))
        image = tf.image.resize(tf.cast(image, tf.float32), IMAGE_SHAPE[:2],
                                method="bilinear", antialias=False)
        return image, label

    ds = ds.map(decode, num_parallel_calls=tf.data.AUTOTUNE, deterministic=True)
    ds = ds.batch(batch_size, drop_remainder=False)
    if training:
        L = tf.keras.layers
        geometric = {"fill_mode": "reflect", "interpolation": "bilinear"}
        transforms = [
            L.RandomRotation(15 / 360, seed=seed + 1, **geometric),
            L.RandomTranslation(0.10, 0.10, seed=seed + 2, **geometric),
            L.RandomZoom((-0.10, 0.10), width_factor=None, seed=seed + 3, **geometric),
            L.RandomBrightness(0.15, value_range=(0, 255), seed=seed + 4),
            L.RandomContrast(0.15, seed=seed + 5),
        ]
        noise = tf.random.Generator.from_seed(seed + 6)

        def augment(images, labels):
            for transform in transforms:
                images = tf.clip_by_value(transform(images, training=True), 0.0, 255.0)
            images = tf.clip_by_value(images + noise.normal(tf.shape(images), stddev=2.55),
                                      0.0, 255.0)
            return images, labels

        ds = ds.map(augment, num_parallel_calls=1, deterministic=True)
    return ds.prefetch(1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("/home/aracel/Downloads/Skripsi/pengembangan_model/01_data"))
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    parts, weights, report, related = load_inputs(args.root)
    report["pipeline"] = {
        "seed": 42, "batch_size_check": 16, "resize": "bilinear", "antialias": False,
        "rotation_degrees": [-15, 15], "translation_fraction": [-0.10, 0.10],
        "zoom_keras_factor": [-0.10, 0.10], "brightness_delta": [-38.25, 38.25],
        "contrast_factor": [0.85, 1.15], "noise_stddev": 2.55, "fill_mode": "reflect",
        "transform_seed_offsets": [1, 2, 3, 4, 5, 6], "augmentation_train_only": True,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    related.to_csv(args.out / "related_cross_split.csv", index=False)
    save_json(args.out / "class_names.json", CLASSES)
    save_json(args.out / "class_weights.json", weights)
    if not args.metadata_only:
        tf = configure_runtime(42)
        report["tensorflow"] = tf.__version__
        report["batch_checks"] = {}
        for name in ("train", "validation"):
            ds = make_dataset(args.root, parts[name], training=name == "train")
            images, labels = next(iter(ds))
            require(tuple(images.shape[1:]) == IMAGE_SHAPE and images.dtype == tf.float32,
                    "Kontrak bentuk/tipe tensor tidak sesuai.")
            tf.debugging.assert_all_finite(images, "Piksel memuat NaN/Inf.")
            tf.debugging.assert_greater_equal(images, 0.0)
            tf.debugging.assert_less_equal(images, 255.0)
            report["batch_checks"][name] = {"shape": images.shape.as_list(),
                                           "min": float(tf.reduce_min(images)),
                                           "max": float(tf.reduce_max(images))}
    save_json(args.out / "data_check.json", report)
    print(json.dumps(report, indent=2))
    if report["parent_groups_cross_split"]:
        print("CATATAN: crop dari gambar asal yang sama terdapat lintas partisi; lihat related_cross_split.csv.")


if __name__ == "__main__":
    main()
