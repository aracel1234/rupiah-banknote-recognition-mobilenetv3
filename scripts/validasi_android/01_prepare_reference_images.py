#!/usr/bin/env python3

from pathlib import Path
import hashlib
import random
import shutil

import pandas as pd


# ============================================================
# KONFIGURASI
# ============================================================

SEED = 42

PROJECT_ROOT = Path("/home/aracel/Downloads/Skripsi")

MANIFEST_PATH = (
    PROJECT_ROOT
    / "persiapan_data"
    / "05_dataset"
    / "validation_manifest.csv"
)

DATA_ROOT = PROJECT_ROOT / "persiapan_data"

OUTPUT_ROOT = (
    PROJECT_ROOT
    / "laporan_skripsi"
    / "Aset Penulisan bab 5.6"
    / "Validasi Inferensi"
)

REFERENCE_DIR = OUTPUT_ROOT / "reference_images"
OUTPUT_MANIFEST = OUTPUT_ROOT / "reference_manifest.csv"
OUTPUT_SUMMARY = OUTPUT_ROOT / "reference_selection_summary.csv"


# ============================================================
# FUNGSI BANTU
# ============================================================

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def resolve_image(relative_path: str) -> Path:
    path = DATA_ROOT / relative_path

    if not path.is_file():
        raise FileNotFoundError(
            "\nCitra tidak ditemukan.\n"
            f"Manifest path : {relative_path}\n"
            f"Resolved path : {path}"
        )

    return path


def validate_class_mapping(df: pd.DataFrame) -> None:
    mapping = (
        df[["class_index", "label"]]
        .drop_duplicates()
        .sort_values("class_index")
    )

    expected = [
        (0, "1000"),
        (1, "2000"),
        (2, "5000"),
        (3, "10000"),
        (4, "20000"),
        (5, "50000"),
        (6, "100000"),
        (7, "nonuang"),
    ]

    actual = [
        (int(row.class_index), str(row.label))
        for row in mapping.itertuples(index=False)
    ]

    if actual != expected:
        raise RuntimeError(
            "\nMapping kelas tidak sesuai kontrak Android.\n"
            f"Expected : {expected}\n"
            f"Actual   : {actual}"
        )


# ============================================================
# PEMILIHAN SAMPEL
# ============================================================

def select_reference_images(df: pd.DataFrame) -> pd.DataFrame:
    rng = random.Random(SEED)

    selected_rows = []

    classes = (
        df[["class_index", "label"]]
        .drop_duplicates()
        .sort_values("class_index")
    )

    for row in classes.itertuples(index=False):

        class_index = int(row.class_index)
        label = str(row.label)

        class_df = (
            df[
                (df["class_index"] == class_index)
                & (df["label"] == label)
            ]
            .copy()
            .sort_values("sample_id")
            .reset_index(drop=True)
        )

        sources = sorted(
            class_df["source_id"]
            .dropna()
            .unique()
            .tolist()
        )

        # ====================================================
        # KELAS NOMINAL
        # Wajib dua source_id berbeda
        # ====================================================

        if label != "nonuang":

            if len(sources) < 2:
                raise RuntimeError(
                    f"Kelas {label} hanya mempunyai "
                    f"{len(sources)} source_id."
                )

            chosen_sources = rng.sample(sources, 2)

            for source_id in chosen_sources:

                candidates = (
                    class_df[
                        class_df["source_id"] == source_id
                    ]
                    .sort_values("sample_id")
                    .reset_index(drop=True)
                )

                chosen_idx = rng.randrange(len(candidates))
                chosen = candidates.iloc[chosen_idx].copy()

                chosen["selection_rule"] = "distinct_source_id"
                chosen["source_distinct"] = True
                chosen["methodological_note"] = (
                    "Dua citra kelas nominal dipilih dari "
                    "source_id yang berbeda."
                )

                selected_rows.append(chosen)

        # ====================================================
        # KELAS NONUANG
        #
        # Seluruh data validasi nonuang berasal dari ds11.
        # Oleh karena itu dipilih dua sample_id berbeda dari
        # source_id yang sama dan pengecualian dicatat.
        # ====================================================

        else:

            if len(class_df) < 2:
                raise RuntimeError(
                    "Kelas nonuang tidak memiliki minimal "
                    "dua sampel validasi."
                )

            selected_indices = rng.sample(
                range(len(class_df)),
                2,
            )

            for idx in selected_indices:
                chosen = class_df.iloc[idx].copy()

                chosen["selection_rule"] = (
                    "distinct_sample_same_source"
                )
                chosen["source_distinct"] = False
                chosen["methodological_note"] = (
                    "Seluruh data validasi kelas nonuang "
                    "berasal dari satu source_id, yaitu ds11. "
                    "Oleh karena itu digunakan dua sample_id "
                    "berbeda dari ds11."
                )

                selected_rows.append(chosen)

    return pd.DataFrame(selected_rows)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 78)
    print("PREPARASI 16 CITRA REFERENSI VALIDASI INTEGRASI")
    print("=" * 78)

    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            f"Manifest tidak ditemukan: {MANIFEST_PATH}"
        )

    df = pd.read_csv(
        MANIFEST_PATH,
        dtype={
            "sample_id": str,
            "label": str,
            "source_id": str,
            "file_path": str,
        },
    )

    required_columns = {
        "sample_id",
        "label",
        "source_id",
        "file_path",
        "class_index",
        "split",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise RuntimeError(
            f"Kolom manifest tidak lengkap: {sorted(missing)}"
        )

    df = df[df["split"] == "validation"].copy()

    if len(df) != 4378:
        print(
            "PERINGATAN: jumlah validation bukan 4378. "
            f"Ditemukan {len(df)}."
        )

    validate_class_mapping(df)

    selected = select_reference_images(df)

    # ========================================================
    # VALIDASI PEMILIHAN
    # ========================================================

    if len(selected) != 16:
        raise RuntimeError(
            f"Diharapkan 16 citra, tetapi diperoleh "
            f"{len(selected)}."
        )

    class_counts = selected.groupby("class_index").size()

    if not (class_counts == 2).all():
        raise RuntimeError(
            "Tidak semua kelas memiliki tepat dua citra."
        )

    if selected["sample_id"].duplicated().any():
        raise RuntimeError(
            "Terdapat sample_id yang terpilih lebih dari sekali."
        )

    # Kelas nominal harus memiliki dua source berbeda
    nominal = selected[selected["label"] != "nonuang"]

    nominal_sources = (
        nominal.groupby("class_index")["source_id"]
        .nunique()
    )

    if not (nominal_sources == 2).all():
        raise RuntimeError(
            "Ada kelas nominal yang tidak memiliki "
            "dua source_id berbeda."
        )

    # Kelas nonuang harus dua sample tetapi memang satu source
    nonuang = selected[selected["label"] == "nonuang"]

    if len(nonuang) != 2:
        raise RuntimeError(
            "Kelas nonuang harus memiliki dua citra."
        )

    if nonuang["sample_id"].nunique() != 2:
        raise RuntimeError(
            "Dua citra nonuang bukan sample_id berbeda."
        )

    # ========================================================
    # SIAPKAN OUTPUT
    # ========================================================

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if REFERENCE_DIR.exists():
        shutil.rmtree(REFERENCE_DIR)

    REFERENCE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected = (
        selected
        .sort_values(
            ["class_index", "source_id", "sample_id"]
        )
        .reset_index(drop=True)
    )

    output_rows = []

    # ========================================================
    # COPY 16 CITRA + HASH
    # ========================================================

    for i, row in selected.iterrows():

        reference_id = f"REF_{i + 1:03d}"

        source_path = resolve_image(
            row["file_path"]
        )

        extension = source_path.suffix.lower()

        safe_label = (
            str(row["label"])
            .replace("/", "_")
            .replace(" ", "_")
        )

        output_name = (
            f"{reference_id}"
            f"_c{int(row['class_index']):02d}"
            f"_{safe_label}"
            f"_{row['source_id']}"
            f"{extension}"
        )

        destination = (
            REFERENCE_DIR
            / output_name
        )

        shutil.copy2(
            source_path,
            destination,
        )

        source_sha = sha256_file(source_path)
        copy_sha = sha256_file(destination)

        if source_sha != copy_sha:
            raise RuntimeError(
                f"SHA-256 berbeda setelah copy: "
                f"{reference_id}"
            )

        output_rows.append(
            {
                "reference_id": reference_id,
                "sample_id": row["sample_id"],
                "class_index": int(
                    row["class_index"]
                ),
                "label": str(row["label"]),
                "source_id": str(row["source_id"]),
                "selection_rule": row[
                    "selection_rule"
                ],
                "source_distinct": bool(
                    row["source_distinct"]
                ),
                "original_relative_path": row[
                    "file_path"
                ],
                "reference_file": output_name,
                "sha256": copy_sha,
                "selection_seed": SEED,
                "methodological_note": row[
                    "methodological_note"
                ],
            }
        )

    result = pd.DataFrame(output_rows)

    # ========================================================
    # SIMPAN MANIFEST
    # ========================================================

    result.to_csv(
        OUTPUT_MANIFEST,
        index=False,
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    summary = (
        result
        .groupby(
            ["class_index", "label"],
            as_index=False,
        )
        .agg(
            jumlah_citra=(
                "reference_id",
                "count",
            ),
            jumlah_source=(
                "source_id",
                "nunique",
            ),
            sample_unik=(
                "sample_id",
                "nunique",
            ),
        )
    )

    summary["aturan_terpenuhi"] = summary.apply(
        lambda r:
            (
                r["jumlah_citra"] == 2
                and r["jumlah_source"] == 2
            )
            if r["label"] != "nonuang"
            else
            (
                r["jumlah_citra"] == 2
                and r["sample_unik"] == 2
            ),
        axis=1,
    )

    summary.to_csv(
        OUTPUT_SUMMARY,
        index=False,
    )

    # ========================================================
    # OUTPUT TERMINAL
    # ========================================================

    print("\n16 CITRA TERPILIH:\n")

    print(
        result[
            [
                "reference_id",
                "class_index",
                "label",
                "source_id",
                "sample_id",
                "selection_rule",
            ]
        ].to_string(index=False)
    )

    print("\n" + "=" * 78)
    print("RINGKASAN")
    print("=" * 78)

    print(summary.to_string(index=False))

    print("\nOutput:")
    print(f"Manifest : {OUTPUT_MANIFEST}")
    print(f"Summary  : {OUTPUT_SUMMARY}")
    print(f"Images   : {REFERENCE_DIR}")

    print("\nValidasi akhir:")
    print(f"Jumlah citra : {len(result)}")
    print(
        f"Jumlah kelas : "
        f"{result['class_index'].nunique()}"
    )
    print(
        "Sample unik  : "
        f"{result['sample_id'].nunique()}"
    )
    print(
        "Semua aturan : "
        f"{summary['aturan_terpenuhi'].all()}"
    )

    print("\nCATATAN:")
    print(
        "- Kelas nominal: dua source_id berbeda."
    )
    print(
        "- Kelas nonuang: dua sample_id berbeda "
        "dari ds11 karena seluruh data nonuang "
        "hanya memiliki satu source_id."
    )


if __name__ == "__main__":
    main()