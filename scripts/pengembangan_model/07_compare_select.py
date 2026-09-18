"""Tahap 7: validasi penuh, benchmark Android, seleksi Pareto/leksikografis, lalu konfirmasi test."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf

from selection_checks import (
    protocol_template, select_with_uncertainty, tree_hash, validate_benchmark, validate_protocol,
)

BASE = Path("/home/aracel/Downloads/Skripsi/pengembangan_model")
NAMES = ("fp32", "fp16", "dynamic_range", "full_int8")

def _load_local(alias, filename):
    import importlib.util, sys
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module

_dp = _load_local("data_pipeline", "01_data_pipeline.py")
CLASSES, DEFAULT_ROOT = _dp.CLASSES, _dp.DEFAULT_ROOT
load_inputs, make_dataset = _dp.load_inputs, _dp.make_dataset
require, save_json, sha256 = _dp.require, _dp.save_json, _dp.sha256

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def group_ids(frame):
    sample = frame["sample_id"].astype(str)
    fallback = sample.where(frame["label"].eq("nonuang"), sample.str.replace(r"_ann\d+$", "", regex=True))
    if "parent_id" in frame.columns:
        parent = frame["parent_id"].fillna("").astype(str)
        return parent.where(parent.ne(""), fallback)
    return fallback

def runners(manifest):
    packs = {}
    for row in manifest.itertuples():
        require(sha256(row.model_path) == row.sha256 and str(row.valid).lower() == "true", f"Artefak {row.candidate} tidak valid/berubah.")
        interpreter = tf.lite.Interpreter(
            model_path=row.model_path,
            num_threads=1,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
        )
        interpreter.allocate_tensors()
        ins, outs = interpreter.get_input_details(), interpreter.get_output_details()
        require(len(ins) == len(outs) == 1, "Antarmuka model berubah.")
        expected = np.int8 if row.candidate == "full_int8" else np.float32
        require(ins[0]["shape"].tolist() == [1, 224, 224, 3] and outs[0]["shape"].tolist() == [1, 8], "Shape salah.")
        require(ins[0]["dtype"] == outs[0]["dtype"] == expected, "Dtype salah.")
        if expected == np.int8:
            require(all(np.isfinite(d["quantization"][0]) and d["quantization"][0] > 0 for d in (ins[0], outs[0])), "Skala kuantisasi salah.")
        packs[row.candidate] = (interpreter, ins[0], outs[0])
    return packs

def invoke(pack, x):
    interpreter, input_detail, output_detail = pack
    if input_detail["dtype"] == np.int8:
        scale, zero = input_detail["quantization"]
        x = np.clip(np.rint(x / scale + zero), -128, 127).astype(np.int8)
    else:
        x = x.astype(np.float32)
    interpreter.set_tensor(input_detail["index"], x[None, ...])
    interpreter.invoke()
    y = interpreter.get_tensor(output_detail["index"])[0]
    if output_detail["dtype"] == np.int8:
        scale, zero = output_detail["quantization"]
        y = scale * (y.astype(np.float32) - zero)
    require(y.shape == (8,) and np.isfinite(y).all(), "Probabilitas model tidak valid.")
    return y.astype(np.float32)

def predict(root, frame, packs):
    truth, seen = frame["class_index"].to_numpy(np.int32), []
    probabilities = {name: [] for name in NAMES}
    for images, labels in make_dataset(root, frame, batch_size=32, training=False, seed=42):
        array = images.numpy()
        seen.extend(labels.numpy().tolist())
        for image in array:
            for name in NAMES:
                probabilities[name].append(invoke(packs[name], image))
    require(np.array_equal(truth, np.asarray(seen, np.int32)), "Urutan evaluasi berubah.")
    return truth, {name: np.stack(probabilities[name]) for name in NAMES}

def cm_metrics(y, pred):
    cm = np.bincount(y * 8 + pred, minlength=64).reshape(8, 8)
    tp = np.diag(cm).astype(float)
    support, guessed = cm.sum(1).astype(float), cm.sum(0).astype(float)
    precision = np.divide(tp, guessed, out=np.zeros(8), where=guessed > 0)
    recall = np.divide(tp, support, out=np.zeros(8), where=support > 0)
    f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros(8), where=(precision + recall) > 0)
    metrics = {
        "accuracy": float(tp.sum() / cm.sum()),
        "macro_precision": float(precision.mean()),
        "macro_recall": float(recall.mean()),
        "macro_f1": float(f1.mean()),
        "weighted_f1": float(np.average(f1, weights=support)),
        "min_recall": float(recall.min()),
    }
    return cm, precision, recall, f1, metrics

def macro_f1(y, pred):
    return cm_metrics(y, pred)[4]["macro_f1"]

def plot_cm(cm, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(cm)
    ax.set(xticks=range(8), yticks=range(8), xticklabels=CLASSES, yticklabels=CLASSES,
           xlabel="Prediksi", ylabel="Aktual", title=title)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    for i in range(8):
        for j in range(8):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)

def bootstrap(frame, y, predictions, iterations, seed, grouped=True):
    gids = group_ids(frame).to_numpy() if grouped else frame["sample_id"].to_numpy()
    require(pd.DataFrame({"g": gids, "y": y}).groupby("g")["y"].nunique().max() == 1, "Satu group memuat lebih dari satu kelas.")
    groups = []
    for cls in range(8):
        idx = np.where(y == cls)[0]
        unique = pd.Series(gids[idx]).drop_duplicates().tolist()
        groups.append([idx[gids[idx] == gid] for gid in unique])
    rng, rows = np.random.default_rng(seed), []
    for iteration in range(iterations):
        pieces = []
        for pool in groups:
            picks = rng.integers(0, len(pool), size=len(pool))
            pieces.extend(pool[j] for j in picks)
        ix = np.concatenate(pieces)
        rows.append({"iteration": iteration + 1, **{name: macro_f1(y[ix], predictions[name][ix]) for name in NAMES}})
    return pd.DataFrame(rows)

def analyze_set(name, frame, y, probs, out, seed):
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    rows, per_class, preds = [], [], {}
    table = frame[["sample_id", "label", "class_index"]].copy()
    table["group_id"] = group_ids(frame)
    for candidate in NAMES:
        pred = np.argmax(probs[candidate], axis=1).astype(np.int32)
        preds[candidate] = pred
        cm, precision, recall, f1, metrics = cm_metrics(y, pred)
        rows.append({"candidate": candidate, **metrics})
        for index, label in enumerate(CLASSES):
            per_class.append({"candidate": candidate, "class_index": index, "label": label,
                              "precision": precision[index], "recall": recall[index], "f1": f1[index],
                              "support": int(cm[index].sum())})
        pd.DataFrame(cm, index=CLASSES, columns=CLASSES).to_csv(folder / f"confusion_matrix_{candidate}.csv")
        plot_cm(cm, f"Confusion Matrix {name.title()} - {candidate}", folder / f"confusion_matrix_{candidate}.png")
        table[f"pred_{candidate}"] = pred
        table[f"confidence_{candidate}"] = probs[candidate].max(1)
    summary = pd.DataFrame(rows)
    summary.to_csv(folder / "metrics_summary.csv", index=False)
    pd.DataFrame(per_class).to_csv(folder / "per_class_metrics.csv", index=False)
    table.to_csv(folder / "predictions.csv", index=False)
    boot = bootstrap(frame, y, preds, 2000, seed, grouped=name == "validation")
    boot.to_csv(folder / "bootstrap_macro_f1.csv", index=False)
    bootstrap_summary = []
    for candidate in NAMES:
        values = boot[candidate].to_numpy()
        bootstrap_summary.append({"candidate": candidate, "bootstrap_mean": values.mean(), "se": values.std(ddof=1),
                                  "ci95_low": np.percentile(values, 2.5), "ci95_high": np.percentile(values, 97.5)})
    bootstrap_summary = pd.DataFrame(bootstrap_summary)
    bootstrap_summary.to_csv(folder / "bootstrap_summary.csv", index=False)
    return summary, bootstrap_summary

def cache_predictions(name, root, frame, packs, folder, identity):
    path, meta = folder / f"{name}_probabilities.npz", folder / f"{name}_cache.json"
    cached = read_json(meta) if meta.exists() else {}
    if path.exists() and cached.get("identity") == identity:
        require(cached.get("npz_sha256") == sha256(path), "Hash cache berubah.")
        with np.load(path, allow_pickle=False) as data:
            y, probs = data["truth"], {candidate: data[candidate] for candidate in NAMES}
        require(np.array_equal(y, frame.class_index.to_numpy()), "Label cache berubah.")
        require(all(array.shape == (len(y), 8) and np.isfinite(array).all() for array in probs.values()), "Cache rusak.")
        return y, probs
    y, probs = predict(root, frame, packs)
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as handle:
        np.savez_compressed(handle, truth=y, **probs)
    temp.replace(path)
    save_json(meta, {"identity": identity, "npz_sha256": sha256(path)})
    return y, probs

def load_image(root, relative_path):
    raw = tf.io.read_file(str(Path(root) / relative_path))
    image = tf.io.decode_image(raw, channels=3, expand_animations=False)
    image.set_shape((None, None, 3))
    image = tf.image.resize(tf.cast(image, tf.float32), (224, 224), method="bilinear", antialias=False)
    return image.numpy().astype("<f4")

def export_android_bundle(root, smoke, run6, manifest, out):
    bundle = out / "android_bundle" / "stage7"
    identity_path = out / "android_bundle_identity.json"
    if bundle.exists() and identity_path.exists():
        identity = read_json(identity_path)
        require(tree_hash(bundle) == identity["sha256"], "Bundle Android Tahap 7 berubah; hapus folder 07_compare dan ulangi persiapan.")
        return bundle, identity["sha256"]
    require(not bundle.exists(), "Bundle Android ada tanpa identity; arsipkan/hapus folder 07_compare sebelum mengulang.")
    bundle.mkdir(parents=True)
    rows = []
    for index, row in enumerate(smoke.itertuples()):
        filename = f"input_{index:03d}.f32"
        path = bundle / filename
        load_image(root, row.file_path).tofile(path)
        rows.append({"tensor_index": index, "sample_id": row.sample_id, "label": row.label,
                     "class_index": int(row.class_index), "group_id": row.group_id,
                     "file_name": filename, "sha256": sha256(path)})
    pd.DataFrame(rows).to_csv(bundle / "inputs_manifest.csv", index=False)
    shutil.copy2(run6 / "class_names.json", bundle / "class_names.json")
    candidates = []
    for row in manifest.itertuples():
        source = Path(row.model_path)
        destination = bundle / source.name
        shutil.copy2(source, destination)
        contract_path = run6 / f"tensor_contract_{row.candidate}.json"
        shutil.copy2(contract_path, bundle / contract_path.name)
        contract = read_json(contract_path)
        candidates.append({
            "candidate": row.candidate,
            "file_name": source.name,
            "model_sha256": row.sha256,
            "input_dtype": contract["input_dtype"],
            "output_dtype": contract["output_dtype"],
            "input_quantization": contract["input_quantization"],
            "output_quantization": contract["output_quantization"],
        })
    save_json(bundle / "benchmark_spec.json", {
        "stage": 7,
        "device": "POCO X5 Pro 5G",
        "execution": "CPU_XNNPACK",
        "threads": 4,
        "input_count": 80,
        "input_shape": [1, 224, 224, 3],
        "input_domain": "RGB float32 [0,255] before candidate-specific quantization",
        "warmup_latency": 30,
        "stable_inference_per_session": 500,
        "sessions": 5,
        "memory_warmup": 20,
        "memory_active_seconds": 30,
        "candidates": candidates,
    })
    digest = tree_hash(bundle)
    save_json(identity_path, {"path": str(bundle), "sha256": digest, "input_count": 80})
    return bundle, digest

def android_stats(latency_path, memory_path, manifest, out):
    latency, memory = pd.read_csv(latency_path), pd.read_csv(memory_path)
    validate_benchmark(latency, memory, manifest)
    hashes = dict(zip(manifest.candidate, manifest.sha256))
    for frame, value in ((latency, "time_ms"), (memory, "total_pss_kb")):
        require(set(frame.candidate) == set(NAMES) and frame[value].notna().all(), "Data benchmark Android belum lengkap.")
        require(all(frame.loc[frame.candidate.eq(name), "model_sha256"].eq(hashes[name]).all() for name in NAMES), "Hash model benchmark tidak sesuai.")
    latency_rows = []
    for candidate in NAMES:
        data = latency[latency.candidate.eq(candidate)]
        stable = data[data.measurement_type.eq("stable")].time_ms.to_numpy(float)
        require(len(stable) == 2500 and all(len(data[(data.session.eq(s)) & data.measurement_type.eq("stable")]) == 500 for s in range(1, 6)), f"Latensi {candidate} harus 5x500.")
        init = data[data.measurement_type.eq("initialization")].time_ms.to_numpy(float)
        first = data[data.measurement_type.eq("first_inference")].time_ms.to_numpy(float)
        latency_rows.append({"candidate": candidate, "initialization_mean_ms": init.mean(), "first_inference_mean_ms": first.mean(),
                             "mean_ms": stable.mean(), "median_ms": np.median(stable), "std_ms": stable.std(ddof=1),
                             "min_ms": stable.min(), "max_ms": stable.max(), "p95_ms": np.percentile(stable, 95)})
    latency_summary = pd.DataFrame(latency_rows)
    latency_summary.to_csv(out / "android_latency_summary.csv", index=False)
    stable = latency[latency.measurement_type.eq("stable")].pivot(index=["session", "index", "tensor_index"], columns="candidate", values="time_ms")
    require(stable.notna().all().all() and len(stable) == 2500, "Pengukuran latensi tidak berpasangan lengkap.")
    sessions = []
    for candidate in NAMES:
        for session in range(1, 6):
            data = memory[(memory.candidate.eq(candidate)) & (memory.session.eq(session))]
            baseline = data[data.phase.eq("baseline")].total_pss_kb.to_numpy(float)
            active = data[data.phase.eq("active")].total_pss_kb.to_numpy(float)
            require(len(baseline) == 5 and len(active) == 15, f"PSS {candidate} sesi {session} harus 5 baseline + 15 aktif.")
            sessions.append({"candidate": candidate, "session": session, "baseline_median_kb": np.median(baseline),
                             "active_median_kb": np.median(active), "additional_pss_kb": np.median(active) - np.median(baseline),
                             "active_max_kb": active.max()})
    session_table = pd.DataFrame(sessions)
    session_table.to_csv(out / "android_memory_per_session.csv", index=False)
    memory_rows = []
    for candidate in NAMES:
        data = session_table[session_table.candidate.eq(candidate)]
        memory_rows.append({"candidate": candidate, "baseline_median_kb": np.median(data.baseline_median_kb),
                            "active_median_kb": np.median(data.active_median_kb),
                            "additional_total_pss_kb": np.median(data.additional_pss_kb),
                            "additional_total_pss_mb": np.median(data.additional_pss_kb) / 1024,
                            "active_max_kb": data.active_max_kb.max()})
    memory_summary = pd.DataFrame(memory_rows)
    memory_summary.to_csv(out / "android_memory_summary.csv", index=False)
    return latency_summary, memory_summary

def pareto_select(quality, manifest, latency, memory, latency_path, memory_path, out):
    eligible = quality[quality.quality_eligible].copy()
    eligible = eligible.merge(manifest[["candidate", "sha256", "size_bytes", "size_mib"]], on="candidate").merge(latency, on="candidate").merge(memory, on="candidate")
    require(len(eligible) > 0, "Tidak ada kandidat yang memenuhi kelayakan kualitas.")
    nondominated = []
    for _, a in eligible.iterrows():
        dominated = False
        for _, b in eligible.iterrows():
            if a.candidate == b.candidate:
                continue
            no_worse = b.macro_f1 >= a.macro_f1 and b.median_ms <= a.median_ms and b.size_bytes <= a.size_bytes and b.additional_total_pss_mb <= a.additional_total_pss_mb
            strict = b.macro_f1 > a.macro_f1 or b.median_ms < a.median_ms or b.size_bytes < a.size_bytes or b.additional_total_pss_mb < a.additional_total_pss_mb
            if no_worse and strict:
                dominated = True
                break
        nondominated.append(not dominated)
    eligible["pareto_nondominated"] = nondominated
    pareto = eligible[eligible.pareto_nondominated]
    require(len(pareto) > 0, "Himpunan Pareto kosong.")
    selected, decisions = select_with_uncertainty(pareto, pd.read_csv(latency_path), pd.read_csv(memory_path))
    save_json(out / "selection_reason.json", decisions)
    pd.DataFrame(decisions["pairs"]).to_csv(out / "android_pairwise_bootstrap.csv", index=False)
    return eligible, selected

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=BASE)
    parser.add_argument("--latency-csv", type=Path)
    parser.add_argument("--memory-csv", type=Path)
    parser.add_argument("--protocol-json", type=Path)
    args = parser.parse_args()

    parts, _, report, _ = load_inputs(args.root)
    stage6 = read_json(args.output_root / "06_tflite/latest.json")
    require(stage6.get("status") == "complete" and stage6.get("all_valid") and stage6.get("ready_for_stage7"), "Tahap 6 belum selesai diverifikasi di Android.")
    require(stage6["data_manifest_sha256"] == report["manifest_sha256"], "Manifest data berubah setelah Tahap 6.")
    run6 = Path(stage6["run_dir"])
    manifest = pd.read_csv(run6 / "conversion_manifest.csv")
    require(len(manifest) == 4 and set(manifest.candidate) == set(NAMES) and manifest.valid.astype(str).str.lower().eq("true").all(), "Empat kandidat valid wajib tersedia.")
    require(read_json(run6 / "class_names.json") == CLASSES, "Urutan kelas berubah.")

    out = args.output_root / "07_compare"
    out.mkdir(parents=True, exist_ok=True)
    identity = {"evaluation_version": 3, "data_manifest_sha256": report["manifest_sha256"],
                "artifact_sha256": dict(zip(manifest.candidate, manifest.sha256))}
    provenance = out / "evaluation_identity.json"
    if provenance.exists():
        require(read_json(provenance) == identity, "Artefak berubah. Arsipkan folder 07_compare sebelum evaluasi versi baru.")
    else:
        save_json(provenance, identity)

    if (out / "latest.json").exists() and args.latency_csv is None and args.memory_csv is None:
        old = read_json(out / "latest.json")
        if old.get("status") == "complete":
            require(sha256(out / "selection_lock.json") == old["selection_lock_sha256"], "Lock berubah.")
            print(json.dumps(old, indent=2, ensure_ascii=False))
            return

    packs = runners(manifest)
    y_validation, p_validation = cache_predictions("validation", args.root, parts["validation"], packs, out, identity)
    validation, bootstrap_summary = analyze_set("validation", parts["validation"], y_validation, p_validation, out, 42)
    best = validation.loc[validation.macro_f1.idxmax(), "candidate"]
    se = float(bootstrap_summary.loc[bootstrap_summary.candidate.eq(best), "se"].iloc[0])
    threshold = float(validation.loc[validation.candidate.eq(best), "macro_f1"].iloc[0] - se)
    quality = validation.merge(bootstrap_summary, on="candidate")
    quality["one_se_threshold"] = threshold
    quality["quality_eligible"] = (quality.macro_f1 >= threshold) & (quality.min_recall > 0)
    quality.to_csv(out / "quality_eligibility.csv", index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4))
    x = np.arange(len(NAMES))
    q = quality.set_index("candidate").loc[list(NAMES)]
    ax.vlines(x, q.ci95_low, q.ci95_high)
    ax.scatter(x, q.macro_f1)
    ax.axhline(threshold, linestyle="--", label=f"Batas 1-SE = {threshold:.4f}")
    ax.set(xticks=x, xticklabels=NAMES, ylabel="Macro F1", title="Kelayakan Kualitas Kandidat")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "validation_macro_f1_ci.png", dpi=180)
    plt.close(fig)

    sizes = manifest[["candidate", "sha256", "size_bytes", "size_mib"]].copy()
    fp32_bytes = float(sizes.loc[sizes.candidate.eq("fp32"), "size_bytes"].iloc[0])
    sizes["reduction_vs_fp32_pct"] = (fp32_bytes - sizes.size_bytes.astype(float)) / fp32_bytes * 100.0
    sizes.to_csv(out / "model_size_summary.csv", index=False)

    smoke = pd.read_csv(run6 / "validation_smoke_manifest.csv", dtype={"label": str})
    require(len(smoke) == 80 and smoke.groupby("label").size().reindex(CLASSES).eq(10).all(), "Input benchmark harus 80, 10 per kelas.")
    require("group_id" in smoke.columns and not smoke.group_id.duplicated().any(), "Input benchmark harus berasal dari 80 group berbeda.")
    shutil.copy2(run6 / "validation_smoke_manifest.csv", out / "android_benchmark_inputs_manifest.csv")
    bundle, bundle_sha256 = export_android_bundle(args.root, smoke, run6, manifest, out)

    waiting = args.latency_csv is None and args.memory_csv is None
    require(waiting or (args.latency_csv is not None and args.memory_csv is not None), "Berikan latency dan memory CSV sekaligus.")
    if waiting:
        template = out / "android_protocol_template.json"
        if not template.exists():
            save_json(template, protocol_template(manifest, bundle_sha256))
        status = {
            "status": "awaiting_android_benchmark", "stage": 7, "test_images_used": 0,
            "quality_best": best, "one_se_threshold": threshold,
            "quality_eligible": quality.loc[quality.quality_eligible, "candidate"].tolist(),
            "android_bundle_path": str(bundle), "android_bundle_sha256": bundle_sha256,
            "next_step": "Jalankan scripts/run_stage7_benchmark.py pada POCO X5 Pro 5G, lalu jalankan ulang file ini dengan CSV latensi, CSV memori, dan protocol JSON.",
        }
        save_json(out / "latest.json", status)
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return

    require(args.protocol_json is not None and args.protocol_json.is_file(), "Berikan --protocol-json dari benchmark Android.")
    protocol = read_json(args.protocol_json)
    validate_protocol(protocol, manifest, args.latency_csv, args.memory_csv, bundle, bundle_sha256)
    latency, memory = android_stats(args.latency_csv, args.memory_csv, manifest, out)
    comparison, selected = pareto_select(quality, manifest, latency, memory, args.latency_csv, args.memory_csv, out)
    comparison.to_csv(out / "candidate_comparison.csv", index=False)

    lock = {
        "status": "locked_before_test", "selected_candidate": selected["candidate"], "model_sha256": selected["sha256"],
        "selection_order": ["artifact_validity", "one_standard_error_quality", "pareto", "lexicographic"],
        "lexicographic_order": ["median_ms", "p95_ms", "size_bytes", "additional_total_pss_mb"],
        "runtime": protocol["runtime"], "protocol_sha256": sha256(args.protocol_json),
        "artifact_sha256": identity["artifact_sha256"], "class_names_sha256": sha256(run6 / "class_names.json"),
        "selection_reason": read_json(out / "selection_reason.json"), "comparison": comparison.to_dict(orient="records"),
        "latency_csv_sha256": sha256(args.latency_csv), "memory_csv_sha256": sha256(args.memory_csv),
        "android_bundle_sha256": bundle_sha256, "data_manifest_sha256": report["manifest_sha256"],
    }
    lock_path = out / "selection_lock.json"
    if lock_path.exists():
        existing = read_json(lock_path)
        require({k: v for k, v in existing.items() if k != "locked_at_utc"} == lock, "Keputusan model sudah dikunci; hasil seleksi tidak boleh diubah setelah test dibuka.")
    else:
        lock["locked_at_utc"] = datetime.now(timezone.utc).isoformat()
        temporary = lock_path.with_suffix(".tmp")
        save_json(temporary, lock)
        temporary.replace(lock_path)
    shutil.copy2(lock_path, out / "model_selection.json")

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(comparison.size_mib, comparison.median_ms)
    for row in comparison.itertuples():
        ax.annotate(row.candidate, (row.size_mib, row.median_ms))
    ax.set(xlabel="Ukuran Model (MiB)", ylabel="Median Inferensi Android (ms)", title="Kandidat Layak Kualitas")
    fig.tight_layout()
    fig.savefig(out / "pareto_latency_size.png", dpi=180)
    plt.close(fig)

    test_identity = dict(identity, selection_lock_sha256=sha256(lock_path))
    y_test, p_test = cache_predictions("test", args.root, parts["test"], packs, out, test_identity)
    test, _ = analyze_set("test", parts["test"], y_test, p_test, out, 2026)
    gap = validation[["candidate", "accuracy", "macro_f1", "weighted_f1"]].merge(
        test[["candidate", "accuracy", "macro_f1", "weighted_f1"]], on="candidate", suffixes=("_validation", "_test"))
    for metric in ("accuracy", "macro_f1", "weighted_f1"):
        gap[f"{metric}_gap"] = gap[f"{metric}_validation"] - gap[f"{metric}_test"]
    gap.to_csv(out / "validation_test_gap.csv", index=False)

    final = out / "final_assets"
    final.mkdir(exist_ok=True)
    row = manifest.loc[manifest.candidate.eq(selected["candidate"])].iloc[0]
    shutil.copy2(row.model_path, final / "model.tflite")
    shutil.copy2(run6 / "class_names.json", final / "class_names.json")
    shutil.copy2(run6 / f"tensor_contract_{selected['candidate']}.json", final / "tensor_contract.json")
    save_json(final / "model_identity.json", {"candidate": selected["candidate"], "sha256": sha256(final / "model.tflite"), "source_stage6_sha256": row.sha256})
    status = {"status": "complete", "stage": 7, "selected_candidate": selected["candidate"],
              "selected_model_sha256": row.sha256, "test_images_used": len(parts["test"]),
              "final_assets": str(final), "data_manifest_sha256": report["manifest_sha256"],
              "selection_lock_sha256": sha256(lock_path)}
    save_json(out / "latest.json", status)
    print(json.dumps(status, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
