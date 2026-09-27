#!/usr/bin/env python3

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean


SCORE_COLS = [f"score_{i}" for i in range(8)]

CORE_EQUAL_FIELDS = [
    "reference_id",
    "sample_id",
    "true_class_index",
    "true_label",
    "source_id",
    "reference_file",
    "image_sha256",
    "model_sha256",
    "input_shape",
    "input_dtype",
    "output_shape",
    "output_dtype",
]


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    result = {}

    for row in rows:
        ref = row["reference_id"]

        if ref in result:
            raise ValueError(f"Duplicate reference_id: {ref} pada {path}")

        result[ref] = row

    return result


def as_bool(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def abs_score_diff(a, b):
    return [
        abs(float(a[col]) - float(b[col]))
        for col in SCORE_COLS
    ]


def pair_metrics(a, b):
    diffs = abs_score_diff(a, b)

    return {
        "mean_abs_score_diff": mean(diffs),
        "max_abs_score_diff": max(diffs),
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--python", required=True)
    parser.add_argument("--poco", required=True)
    parser.add_argument("--redmi", required=True)
    parser.add_argument("--out-dir", required=True)

    args = parser.parse_args()

    py = load_csv(args.python)
    poco = load_csv(args.poco)
    redmi = load_csv(args.redmi)

    refs_py = set(py)
    refs_poco = set(poco)
    refs_redmi = set(redmi)

    if not (refs_py == refs_poco == refs_redmi):
        raise RuntimeError(
            "Daftar reference_id Python, POCO, dan Redmi tidak identik."
        )

    refs = sorted(refs_py)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison_rows = []

    score_diff_py_poco = []
    score_diff_py_redmi = []
    score_diff_poco_redmi = []

    processing_all = True
    contract_all = True
    image_hash_all = True

    top1_py_poco = 0
    top1_py_redmi = 0
    top1_poco_redmi = 0
    top1_all_three = 0

    ground_truth_mismatches = []

    for ref in refs:
        p = py[ref]
        a = poco[ref]
        r = redmi[ref]

        processing_ok = (
            as_bool(p["processing_success"])
            and as_bool(a["processing_success"])
            and as_bool(r["processing_success"])
        )

        processing_all &= processing_ok

        fields_equal = all(
            p[field] == a[field] == r[field]
            for field in CORE_EQUAL_FIELDS
        )

        contract_all &= fields_equal

        image_hash_match = (
            p["image_sha256"]
            == a["image_sha256"]
            == r["image_sha256"]
        )

        image_hash_all &= image_hash_match

        py_poco_match = (
            p["top_index"] == a["top_index"]
            and p["top_label"] == a["top_label"]
        )

        py_redmi_match = (
            p["top_index"] == r["top_index"]
            and p["top_label"] == r["top_label"]
        )

        poco_redmi_match = (
            a["top_index"] == r["top_index"]
            and a["top_label"] == r["top_label"]
        )

        all_three_match = (
            py_poco_match
            and py_redmi_match
            and poco_redmi_match
        )

        top1_py_poco += int(py_poco_match)
        top1_py_redmi += int(py_redmi_match)
        top1_poco_redmi += int(poco_redmi_match)
        top1_all_three += int(all_three_match)

        d1 = pair_metrics(p, a)
        d2 = pair_metrics(p, r)
        d3 = pair_metrics(a, r)

        score_diff_py_poco.extend(abs_score_diff(p, a))
        score_diff_py_redmi.extend(abs_score_diff(p, r))
        score_diff_poco_redmi.extend(abs_score_diff(a, r))

        gt_match_py = p["top_label"] == p["true_label"]
        gt_match_poco = a["top_label"] == a["true_label"]
        gt_match_redmi = r["top_label"] == r["true_label"]

        if not (gt_match_py and gt_match_poco and gt_match_redmi):
            ground_truth_mismatches.append({
                "reference_id": ref,
                "true_label": p["true_label"],
                "python_top_label": p["top_label"],
                "poco_top_label": a["top_label"],
                "redmi_top_label": r["top_label"],
            })

        comparison_rows.append({
            "reference_id": ref,
            "sample_id": p["sample_id"],
            "true_label": p["true_label"],

            "python_top_label": p["top_label"],
            "poco_top_label": a["top_label"],
            "redmi_top_label": r["top_label"],

            "python_top_score": p["top_score"],
            "poco_top_score": a["top_score"],
            "redmi_top_score": r["top_score"],

            "python_poco_top1_match": py_poco_match,
            "python_redmi_top1_match": py_redmi_match,
            "poco_redmi_top1_match": poco_redmi_match,
            "all_three_top1_match": all_three_match,

            "python_poco_mean_abs_score_diff":
                d1["mean_abs_score_diff"],
            "python_poco_max_abs_score_diff":
                d1["max_abs_score_diff"],

            "python_redmi_mean_abs_score_diff":
                d2["mean_abs_score_diff"],
            "python_redmi_max_abs_score_diff":
                d2["max_abs_score_diff"],

            "poco_redmi_mean_abs_score_diff":
                d3["mean_abs_score_diff"],
            "poco_redmi_max_abs_score_diff":
                d3["max_abs_score_diff"],
        })

    comparison_csv = out_dir / "comparison_predictions.csv"

    with open(comparison_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=comparison_rows[0].keys()
        )

        writer.writeheader()
        writer.writerows(comparison_rows)

    n = len(refs)

    summary = {
        "schema_version": 1,
        "purpose": "Python-POCO-Redmi inference equivalence validation",

        "reference_count": n,

        "processing_success_all": processing_all,
        "contract_match_all": contract_all,
        "reference_image_sha256_match_all": image_hash_all,

        "top1_agreement": {
            "python_vs_poco": {
                "count": top1_py_poco,
                "rate": top1_py_poco / n,
            },
            "python_vs_redmi": {
                "count": top1_py_redmi,
                "rate": top1_py_redmi / n,
            },
            "poco_vs_redmi": {
                "count": top1_poco_redmi,
                "rate": top1_poco_redmi / n,
            },
            "all_three": {
                "count": top1_all_three,
                "rate": top1_all_three / n,
            },
        },

        "score_difference": {
            "python_vs_poco": {
                "mean_absolute_difference":
                    mean(score_diff_py_poco),
                "maximum_absolute_difference":
                    max(score_diff_py_poco),
            },

            "python_vs_redmi": {
                "mean_absolute_difference":
                    mean(score_diff_py_redmi),
                "maximum_absolute_difference":
                    max(score_diff_py_redmi),
            },

            "poco_vs_redmi": {
                "mean_absolute_difference":
                    mean(score_diff_poco_redmi),
                "maximum_absolute_difference":
                    max(score_diff_poco_redmi),
            },
        },

        "ground_truth_mismatch_count":
            len(ground_truth_mismatches),

        "ground_truth_mismatches":
            ground_truth_mismatches,
    }

    summary["equivalence_pass"] = (
        processing_all
        and contract_all
        and image_hash_all
        and top1_all_three == n
    )

    summary_path = out_dir / "equivalence_summary.json"

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("=" * 60)
    print("REFERENCE INFERENCE EQUIVALENCE")
    print("=" * 60)
    print(f"Reference             : {n}")
    print(f"Processing success    : {processing_all}")
    print(f"Contract match        : {contract_all}")
    print(f"Image SHA match       : {image_hash_all}")
    print()
    print(f"Python vs POCO        : {top1_py_poco}/{n}")
    print(f"Python vs Redmi       : {top1_py_redmi}/{n}")
    print(f"POCO vs Redmi         : {top1_poco_redmi}/{n}")
    print(f"All three             : {top1_all_three}/{n}")
    print()
    print(
        "Max score diff Python–POCO  : "
        f"{max(score_diff_py_poco):.12g}"
    )
    print(
        "Max score diff Python–Redmi : "
        f"{max(score_diff_py_redmi):.12g}"
    )
    print(
        "Max score diff POCO–Redmi   : "
        f"{max(score_diff_poco_redmi):.12g}"
    )
    print()
    print(
        f"Ground-truth mismatches: "
        f"{len(ground_truth_mismatches)}"
    )
    print()
    print(
        "FINAL STATUS: "
        + ("PASS" if summary["equivalence_pass"] else "FAIL")
    )

    raise SystemExit(
        0 if summary["equivalence_pass"] else 2
    )


if __name__ == "__main__":
    main()