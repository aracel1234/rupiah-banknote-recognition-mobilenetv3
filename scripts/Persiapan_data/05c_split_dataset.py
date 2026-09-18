"""Pembagian 80/10/10 dengan kelompok gambar asal dan stratifikasi kelas.

Jalankan langsung, atau gunakan --root untuk lokasi persiapan_data lain.
Tidak menghapus citra atau mengubah dataset_manifest.csv. Enam keluaran
lama dicadangkan otomatis sebelum diganti. Memerlukan numpy dan pandas.
"""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/home/aracel/Downloads/Skripsi/persiapan_data")
CLASSES = ["1000", "2000", "5000", "10000", "20000", "50000", "100000", "nonuang"]
NAMES = ["train", "validation", "test"]
RATIOS = np.array([0.8, 0.1, 0.1])
SEED = 42
OUTPUTS = [f"{s}_manifest.csv" for s in NAMES] + [
    "split_manifest.csv", "class_weights.json", "stage5c_summary.json"
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parent_ids(df):
    result = []
    for row in df.itertuples(index=False):
        if row.label == "nonuang":
            result.append(f"nonuang:{row.source_id}:{row.sample_id}")
            continue
        match = re.fullmatch(r"(.+)_img(\d+)_ann\d+", row.sample_id)
        require(match is not None, f"Format sample_id uang tidak valid: {row.sample_id}")
        require(match.group(1) == row.source_id,
                f"source_id tidak sesuai sample_id: {row.sample_id}")
        result.append(f"money:{row.source_id}:img{int(match.group(2))}")
    return pd.Series(result, index=df.index, name="parent_id")


def read_inputs(root):
    df = pd.read_csv(root / "05_dataset/dataset_manifest.csv", dtype={"label": str})
    required = ["sample_id", "label", "source_id", "file_path", "class_index"]
    require(set(df.columns) == set(required), "Kolom dataset_manifest tidak sesuai.")
    require(len(df) > 0 and not df.isna().any().any(), "Dataset kosong atau memuat nilai kosong.")
    for column in ["sample_id", "label", "source_id", "file_path"]:
        require(df[column].map(lambda x: isinstance(x, str) and bool(x.strip())).all(),
                f"Nilai {column} tidak valid.")
    for column in ["sample_id", "file_path"]:
        require(df[column].is_unique, f"Terdapat {column} ganda.")
    require(set(df.label) == set(CLASSES), "Delapan kelas tidak lengkap atau ada kelas asing.")
    class_map = dict(zip(CLASSES, range(len(CLASSES))))
    require(df.class_index.eq(df.label.map(class_map)).all(), "class_index tidak sesuai label.")
    money = pd.read_csv(root / "04_dedup/money_unique_manifest.csv", dtype={"label": str})
    require(set(required[:-1] + ["sha256"]).issubset(money.columns), "Kolom manifest uang tidak lengkap.")
    require(money.sample_id.notna().all() and money.sample_id.is_unique,
            "ID pada manifest uang kosong atau ganda.")
    require(money.sha256.astype("string").str.fullmatch(r"[0-9a-fA-F]{64}").fillna(False).all(),
            "SHA-256 uang kosong atau tidak valid.")
    require(money.sha256.str.lower().is_unique, "Masih terdapat SHA-256 uang identik.")
    columns = required[:-1]
    canonical = lambda x: x[columns].sort_values("sample_id").reset_index(drop=True)
    require(canonical(df[df.label.ne("nonuang")]).equals(canonical(money)),
            "Sampel/label/path uang berbeda dari hasil deduplikasi.")
    return df.sort_values(["class_index", "sample_id"]).reset_index(drop=True)


def grouped_split(df, seed=SEED):
    """Alokasi acak berkelompok, lalu perbaiki galat kuadrat proporsi kelas.

    Kelompok dapat berisi lebih dari satu kelas. Seed mengacak urutan kelompok
    berukuran sama dan pemecahan nilai seri. Ini heuristik, bukan optimum global.
    """
    groups = parent_ids(df)
    table = pd.crosstab(groups, df.label).reindex(columns=CLASSES, fill_value=0).sort_index()
    require((table.gt(0).sum(axis=0) >= 3).all(),
            "Setiap kelas perlu sedikitnya tiga kelompok gambar asal.")
    values = table.to_numpy(dtype=np.int64)
    totals = values.sum(axis=0)
    targets = RATIOS[:, None] * totals[None, :]
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(table))
    order = order[np.argsort(-values[order].sum(axis=1), kind="stable")]
    assignment = rng.choice(len(NAMES), size=len(table), p=RATIOS)
    counts = np.zeros_like(targets, dtype=np.int64)
    for part in range(len(NAMES)):
        counts[part] = values[assignment == part].sum(axis=0)
    # Awal acak menghindari semua kelompok besar selalu masuk data latih.
    # Pindahkan hanya kelompok utuh dan hanya bila galat benar-benar turun.
    for _ in range(20):
        changed = False
        for i in order:
            v = values[i]
            origin = assignment[i]
            if np.any((v > 0) & (counts[origin] - v <= 0)):
                continue
            remove = np.sum((-2 * (counts[origin] - targets[origin]) * v + v * v)
                            / (totals * totals))
            delta = remove + np.sum(
                (2 * (counts - targets) * v + v * v) / (totals * totals), axis=1)
            delta[origin] = 0.0
            if delta.min() >= -1e-15:
                continue
            candidates = np.flatnonzero(np.isclose(delta, delta.min(), rtol=0, atol=1e-15))
            chosen = int(rng.choice(candidates))
            counts[origin] -= v
            counts[chosen] += v
            assignment[i] = chosen
            changed = True
        if not changed:
            break
    mapping = pd.Series([NAMES[i] for i in assignment], index=table.index)
    split = df.copy()
    split["split"] = groups.map(mapping)
    require(split.split.notna().all(), "Ada sampel tanpa partisi.")
    require((counts > 0).all(), "Ada kelas kosong pada partisi; pembagian tidak diterbitkan.")
    require(split.groupby(groups)["split"].nunique().eq(1).all(),
            "Kelompok gambar asal tersebar lintas partisi.")
    require(split.sample_id.is_unique and len(split) == len(df), "Integritas partisi gagal.")
    require(split.drop(columns="split").equals(df), "Isi dataset berubah selama pembagian.")
    return split, groups, table


def run(root, seed=SEED):
    root = Path(root)
    out = root / "05_dataset"
    df = read_inputs(root)
    split, groups, table = grouped_split(df, seed)
    parts = {name: split[split.split.eq(name)].reset_index(drop=True) for name in NAMES}
    counts = {name: part.label.value_counts().reindex(CLASSES).astype(int)
              for name, part in parts.items()}
    weights = {label: round(len(parts["train"]) / (len(CLASSES) * int(counts["train"][label])), 8)
               for label in CLASSES}
    totals = df.label.value_counts().reindex(CLASSES)
    error = sum(abs(counts[name][label] - RATIOS[i] * totals[label]) / totals[label]
                for i, name in enumerate(NAMES) for label in CLASSES)
    summary = {
        "seed": seed,
        "split_method": "parent_group_stratified_greedy_v1",
        "allocation_objective": "sum_squared_class_fraction_error",
        "dataset_total": len(df),
        "split_total": {name: len(part) for name, part in parts.items()},
        "split_ratio_target": dict(zip(NAMES, RATIOS.tolist())),
        "split_ratio_actual": {name: round(len(part) / len(df), 6) for name, part in parts.items()},
        "class_counts": {name: c.to_dict() for name, c in counts.items()},
        "class_weights_by_label": weights,
        "distribution_error_J": round(float(error), 8),
        "parent_groups_total": len(table),
        "parent_groups_cross_split": 0,
        "related_samples_cross_split": 0,
        "mixed_label_parent_groups": int(table.gt(0).sum(axis=1).gt(1).sum()),
        "group_counts": {name: int(groups[split.split.eq(name)].nunique()) for name in NAMES},
        "dataset_manifest_sha256": sha256(out / "dataset_manifest.csv"),
        "money_manifest_sha256": sha256(root / "04_dedup/money_unique_manifest.csv"),
        "image_content_checked": False,
        "nonmoney_content_deduplicated": False,
        "ready_for_training": True,
        "readiness_scope": "manifest_integrity_and_known_parent_groups_only",
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
    }
    # Semua validasi selesai sebelum keluaran aktif diganti.
    with tempfile.TemporaryDirectory(prefix=".stage5c_", dir=out) as temporary:
        staged = Path(temporary)
        for name, part in parts.items():
            part.to_csv(staged / f"{name}_manifest.csv", index=False)
        split.to_csv(staged / "split_manifest.csv", index=False)
        for name in NAMES + ["split"]:
            summary[f"{name}_manifest_sha256"] = sha256(staged / f"{name}_manifest.csv")
        (staged / "class_weights.json").write_text(
            json.dumps({str(i): weights[label] for i, label in enumerate(CLASSES)}, indent=2),
            encoding="utf-8")
        (staged / "stage5c_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        existing = [name for name in OUTPUTS if (out / name).exists()]
        backup = None
        if existing:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
            backup = out / "05c_backups" / stamp
            backup.mkdir(parents=True, exist_ok=False)
            for name in existing:
                shutil.copy2(out / name, backup / name)
        replaced = []
        try:
            # Ringkasan beserta hash dipasang terakhir sebagai penanda selesai.
            for name in OUTPUTS:
                (staged / name).replace(out / name)
                replaced.append(name)
        except Exception:
            for name in reversed(replaced):
                if name in existing:
                    shutil.copy2(backup / name, out / name)
                else:
                    (out / name).unlink(missing_ok=True)
            raise
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if backup is not None:
        print(f"Cadangan keluaran 05c sebelumnya: {backup}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    run(args.root, args.seed)


if __name__ == "__main__":
    main()
