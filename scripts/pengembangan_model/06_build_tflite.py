"""Tahap 6: validasi metadata ter-audit, representative set, 4 kandidat TFLite, dan gate Android."""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

import numpy as np
import pandas as pd
import tensorflow as tf

BASE = Path("/home/aracel/Downloads/Skripsi/pengembangan_model")

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
CLASSES, DEFAULT_ROOT, IMAGE_SHAPE = _dp.CLASSES, _dp.DEFAULT_ROOT, _dp.IMAGE_SHAPE
load_inputs, require, save_json, sha256 = _dp.load_inputs, _dp.require, _dp.save_json, _dp.sha256
read_json = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
NAMES = ("fp32", "fp16", "dynamic_range", "full_int8")
FILES = {name: f"mobilenetv3small_{name}.tflite" for name in NAMES}
HUMAN = ("emission_year", "side", "condition", "object_group")
PROXIES = ("brightness_proxy", "orientation_proxy", "scale_proxy")
INVALID_META = {"", "unknown", "not_applicable", "nan", "none"}
ALLOWED = {
    "emission_year": {"unknown", "2016", "2022", "not_applicable"},
    "side": {"unknown", "front", "back", "not_applicable"},
    "condition": {"unknown", "normal", "lusuh", "terlipat", "not_applicable"},
    "object_group": {
        "unknown", "tangan_kosong", "dompet", "kartu", "nota_atau_kertas", "buku",
        "layar_telepon", "kemasan_produk", "latar_kosong", "lainnya", "not_applicable",
    },
}
OBJECT_ALIASES = {
    "tangan": "tangan_kosong",
    "tangan kosong": "tangan_kosong",
    "nota_kertas": "nota_atau_kertas",
    "nota atau kertas": "nota_atau_kertas",
    "layar": "layar_telepon",
    "layar telepon": "layar_telepon",
    "kemasan": "kemasan_produk",
    "kemasan produk": "kemasan_produk",
    "latar kosong": "latar_kosong",
}

def group_ids(df):
    sample = df.sample_id.astype(str)
    return sample.where(df.label.eq("nonuang"), sample.str.replace(r"_ann\d+$", "", regex=True))

def balanced_pool(df, n, seed):
    out, used_groups = [], set()
    frame = df.copy()
    frame["group_id"] = group_ids(frame)
    for k, label in enumerate(CLASSES):
        part = frame[frame.label.eq(label) & ~frame.group_id.isin(used_groups)]
        part = part.drop_duplicates("group_id").sample(frac=1, random_state=seed + k)
        buckets = {source: list(rows.index) for source, rows in part.groupby("source_id", sort=True)}
        picked = []
        while len(picked) < min(n, len(part)):
            moved = False
            for source in sorted(buckets):
                if buckets[source] and len(picked) < n:
                    picked.append(buckets[source].pop())
                    moved = True
            if not moved:
                break
        chosen = frame.loc[picked]
        used_groups.update(chosen.group_id.astype(str))
        out.append(chosen)
    return pd.concat(out, ignore_index=True)

def coco_geometry(root, sample_ids):
    path = Path(root) / "raw_dataset/uang/all_data_merged.json"
    if not path.is_file():
        return {}
    coco = json.loads(path.read_text(encoding="utf-8"))
    images = {int(row["id"]): row for row in coco["images"]}
    annotations = {int(row["id"]): row for row in coco["annotations"]}
    result = {}
    for sample_id in sample_ids:
        match = re.search(r"_ann(\d+)$", str(sample_id))
        if not match:
            continue
        ann_id = int(match.group(1))
        if ann_id not in annotations:
            continue
        ann = annotations[ann_id]
        image_meta = images[int(ann["image_id"])]
        _, _, width, height = ann["bbox"]
        if width <= 0 or height <= 0 or image_meta["width"] <= 0 or image_meta["height"] <= 0:
            continue
        result[str(sample_id)] = (
            float(width / height),
            float((width * height) / (image_meta["width"] * image_meta["height"])),
        )
    return result

def luminance(root, relative_path):
    path = Path(root) / relative_path
    require(path.is_file(), f"Citra tidak ditemukan: {path}")
    image = tf.io.decode_image(tf.io.read_file(str(path)), channels=3, expand_animations=False)
    image = tf.cast(image, tf.float32)
    value = 0.299 * image[..., 0] + 0.587 * image[..., 1] + 0.114 * image[..., 2]
    return float(tf.reduce_mean(value).numpy())

def tertile(series):
    rank = series.rank(method="average", pct=True)
    values = np.where(rank <= 1 / 3, "low", np.where(rank <= 2 / 3, "medium", "high"))
    return pd.Series(values, index=series.index)

def rebuild_automatic_metadata(root, pool):
    pool = pool.copy()
    pool["group_id"] = group_ids(pool)
    geometry = coco_geometry(root, pool.loc[pool.label.ne("nonuang"), "sample_id"])
    pool["aspect_ratio"] = pool.sample_id.map(lambda sid: geometry.get(str(sid), (np.nan, np.nan))[0])
    pool["relative_area"] = pool.sample_id.map(lambda sid: geometry.get(str(sid), (np.nan, np.nan))[1])
    pool["luminance_mean"] = [luminance(root, path) for path in pool.file_path]
    pool["brightness_proxy"] = pool.groupby("label", group_keys=False).luminance_mean.apply(tertile)
    pool["orientation_proxy"] = "not_applicable"
    money = pool.label.ne("nonuang") & pool.aspect_ratio.notna()
    aspect = pool.loc[money, "aspect_ratio"]
    pool.loc[money, "orientation_proxy"] = np.where(
        aspect >= 1.25, "horizontal", np.where(aspect <= 0.80, "vertical", "diagonal_or_square")
    )
    pool["scale_proxy"] = "not_applicable"
    if money.any():
        pool.loc[money, "scale_proxy"] = (
            pool.loc[money].groupby("label", group_keys=False).relative_area.apply(tertile)
        )
    return pool

def normalize_human_metadata(pool):
    pool = pool.copy()
    for column in HUMAN:
        pool[column] = pool[column].astype(str).str.strip().str.lower()
    pool["side"] = pool["side"].replace({"depan": "front", "belakang": "back"})
    pool["object_group"] = pool["object_group"].replace(OBJECT_ALIASES)
    nonmoney = pool.label.eq("nonuang")
    pool.loc[nonmoney, ["emission_year", "side", "condition"]] = "not_applicable"
    pool.loc[~nonmoney, "object_group"] = "not_applicable"
    for column, allowed in ALLOWED.items():
        bad = sorted(set(pool[column]) - allowed)
        require(not bad, f"Nilai metadata {column} tidak valid: {bad[:5]}")
    return pool

def prepare_pool(root, train, n=100, seed=42):
    pool = balanced_pool(train, n, seed)
    for column in HUMAN:
        pool[column] = "unknown"
    pool.loc[pool.label.eq("nonuang"), ["emission_year", "side", "condition"]] = "not_applicable"
    pool.loc[pool.label.ne("nonuang"), "object_group"] = "not_applicable"
    pool["reviewed"] = False
    pool = rebuild_automatic_metadata(root, pool)
    columns = [
        "sample_id", "label", "source_id", "file_path", "group_id", *HUMAN, *PROXIES,
        "luminance_mean", "aspect_ratio", "relative_area", "reviewed",
    ]
    return pool[columns]

def validate_existing_audit(root, train, metadata_path):
    pool = pd.read_csv(metadata_path, dtype=str, keep_default_na=False)
    required = {"sample_id", "label", "source_id", "file_path", *HUMAN}
    require(required <= set(pool.columns), "Kolom metadata hasil audit belum lengkap.")
    require(not pool.sample_id.duplicated().any(), "Metadata audit memiliki sample_id ganda.")
    official = train[["sample_id", "label", "source_id", "file_path"]]
    check = pool.merge(official, on="sample_id", suffixes=("", "_official"), how="left", validate="one_to_one")
    require(check["label_official"].notna().all(), "Metadata audit memuat sampel di luar data train.")
    for column in ("label", "source_id", "file_path"):
        require((check[column] == check[f"{column}_official"]).all(), f"{column} metadata berubah dari manifest train.")
    expected_pool = balanced_pool(train, 100, 42)
    require(set(pool.sample_id) == set(expected_pool.sample_id), "Keanggotaan pool audit berubah; gunakan calibration_metadata_pool.csv hasil --prepare-pool yang sama.")
    pool = normalize_human_metadata(pool)
    pool = rebuild_automatic_metadata(root, pool)
    pool["reviewed"] = pool.get("reviewed", "True")
    return pool

def final_sample(pool, n=50, seed=42):
    out, used_groups = [], set()
    for k, label in enumerate(CLASSES):
        part = pool[pool.label.eq(label) & ~pool.group_id.isin(used_groups)]
        part = part.drop_duplicates("group_id").sample(frac=1, random_state=seed + k).copy()
        seen, source_counts, rows = set(), {}, []
        target = min(n, len(part))
        while len(rows) < target:
            best = None
            for index, row in part.iterrows():
                novelty = sum(
                    str(row[column]).strip().lower() not in INVALID_META
                    and (column, str(row[column])) not in seen
                    for column in (*HUMAN, *PROXIES)
                )
                score = (-source_counts.get(row.source_id, 0), novelty)
                if best is None or score > best[0]:
                    best = (score, index)
            index = best[1]
            row = part.loc[index]
            rows.append(index)
            used_groups.add(str(row.group_id))
            source_counts[row.source_id] = source_counts.get(row.source_id, 0) + 1
            for column in (*HUMAN, *PROXIES):
                value = str(row[column]).strip()
                if value.lower() not in INVALID_META:
                    seen.add((column, value))
            part = part.drop(index)
        out.append(pool.loc[rows])
    return pd.concat(out, ignore_index=True)

def image(root, relative_path):
    path = Path(root) / relative_path
    require(path.is_file(), f"Citra tidak ditemukan: {path}")
    tensor = tf.io.decode_image(tf.io.read_file(str(path)), channels=3, expand_animations=False)
    tensor.set_shape((None, None, 3))
    tensor = tf.image.resize(tf.cast(tensor, tf.float32), IMAGE_SHAPE[:2], method="bilinear", antialias=False)
    tensor = tf.clip_by_value(tensor, 0.0, 255.0)
    return tensor.numpy()[None, ...].astype(np.float32)

def keras_predict(model, root, frame):
    predictions = []
    with tf.device("/CPU:0"):
        for relative_path in frame.file_path:
            predictions.append(model(image(root, relative_path), training=False).numpy()[0].astype(np.float32))
    return np.asarray(predictions, dtype=np.float32)

def tree_hash(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()

def converter(saved_model, name, representative):
    converter_ = tf.lite.TFLiteConverter.from_saved_model(str(saved_model))
    converter_.allow_custom_ops = False
    if name == "fp32":
        converter_.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    elif name == "fp16":
        converter_.optimizations = [tf.lite.Optimize.DEFAULT]
        converter_.target_spec.supported_types = [tf.float16]
        converter_.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    elif name == "dynamic_range":
        converter_.optimizations = [tf.lite.Optimize.DEFAULT]
        converter_.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    else:
        converter_.optimizations = [tf.lite.Optimize.DEFAULT]
        converter_.representative_dataset = representative
        converter_.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter_.inference_input_type = tf.int8
        converter_.inference_output_type = tf.int8
    return converter_.convert()

def inspect_artifact(path, name, analyzer_path):
    interpreter = tf.lite.Interpreter(
        model_path=str(path),
        num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
    )
    interpreter.allocate_tensors()
    inputs, outputs = interpreter.get_input_details(), interpreter.get_output_details()
    require(len(inputs) == 1 and len(outputs) == 1, f"{name}: harus tepat satu input dan satu output.")
    input_detail, output_detail = inputs[0], outputs[0]
    dtype = np.int8 if name == "full_int8" else np.float32
    require(input_detail["shape"].tolist() == [1, 224, 224, 3], f"{name}: input shape salah.")
    require(output_detail["shape"].tolist() == [1, 8], f"{name}: output shape salah.")
    require(input_detail["shape_signature"].tolist() == [1, 224, 224, 3], f"{name}: input shape_signature salah.")
    require(output_detail["shape_signature"].tolist() == [1, 8], f"{name}: output shape_signature salah.")
    require(input_detail["dtype"] == dtype and output_detail["dtype"] == dtype, f"{name}: dtype I/O salah.")
    ops = interpreter._get_ops_details() if hasattr(interpreter, "_get_ops_details") else []
    op_names = [str(row.get("op_name", "")) for row in ops]
    require(not any(op.upper() == "CUSTOM" for op in op_names), f"{name}: memakai CUSTOM op.")
    if name == "full_int8":
        for detail in (input_detail, output_detail):
            scale, zero_point = detail["quantization"]
            require(scale > 0 and -128 <= zero_point <= 127, "Full INT8: parameter kuantisasi I/O tidak valid.")
        tensor_details = interpreter.get_tensor_details()
        require(
            not any(np.issubdtype(detail["dtype"], np.floating) for detail in tensor_details),
            "Full INT8 masih memuat tensor floating-point.",
        )
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        tf.lite.experimental.Analyzer.analyze(model_path=str(path))
    analyzer_path.write_text(buffer.getvalue(), encoding="utf-8")
    contract = {
        "candidate": name,
        "model_sha256": sha256(path),
        "input_shape": input_detail["shape"].tolist(),
        "output_shape": output_detail["shape"].tolist(),
        "input_shape_signature": input_detail["shape_signature"].tolist(),
        "output_shape_signature": output_detail["shape_signature"].tolist(),
        "input_dtype": np.dtype(input_detail["dtype"]).name,
        "output_dtype": np.dtype(output_detail["dtype"]).name,
        "input_quantization": [float(input_detail["quantization"][0]), int(input_detail["quantization"][1])],
        "output_quantization": [float(output_detail["quantization"][0]), int(output_detail["quantization"][1])],
        "class_names": CLASSES,
        "operators": op_names,
    }
    return interpreter, input_detail, output_detail, contract

def infer(interpreter, input_detail, output_detail, tensor):
    if input_detail["dtype"] == np.int8:
        scale, zero_point = input_detail["quantization"]
        require(scale > 0, "Input INT8 scale tidak valid.")
        tensor = np.clip(np.rint(tensor / scale + zero_point), -128, 127).astype(np.int8)
    else:
        tensor = tensor.astype(np.float32)
    interpreter.set_tensor(input_detail["index"], tensor)
    interpreter.invoke()
    output = interpreter.get_tensor(output_detail["index"])
    if output_detail["dtype"] == np.int8:
        scale, zero_point = output_detail["quantization"]
        require(scale > 0, "Output INT8 scale tidak valid.")
        output = scale * (output.astype(np.float32) - zero_point)
    require(output.shape == (1, 8), "Bentuk output inferensi tidak [1,8].")
    require(np.isfinite(output).all(), "Keluaran TFLite memuat NaN/Inf.")
    return output[0].astype(np.float32)

def coverage_csv(rep, path):
    rows = []
    for column in (*HUMAN, *PROXIES):
        for (label, value), count in rep.groupby(["label", column], dropna=False).size().items():
            rows.append({"field": column, "label": label, "value": value, "count": int(count)})
    pd.DataFrame(rows).to_csv(path, index=False)

def metadata_completeness(rep, path):
    rows = []
    for column in (*HUMAN, *PROXIES):
        values = rep[column].astype(str).str.strip().str.lower()
        rows.append({
            "field": column,
            "known": int((~values.isin(INVALID_META)).sum()),
            "unknown": int(values.eq("unknown").sum()),
            "not_applicable": int(values.eq("not_applicable").sum()),
        })
    pd.DataFrame(rows).to_csv(path, index=False)

def build_android_bundle(run, artifacts, smoke, root):
    bundle = run / "android_verification_bundle" / "stage6"
    bundle.mkdir(parents=True, exist_ok=False)
    input_path = bundle / "input_000.f32"
    image(root, smoke.iloc[0].file_path)[0].astype("<f4").tofile(input_path)
    class_path = bundle / "class_names.json"
    save_json(class_path, CLASSES)
    candidates = []
    for name in NAMES:
        source_path, _, _, _, contract = artifacts[name]
        destination = bundle / source_path.name
        shutil.copy2(source_path, destination)
        candidates.append({
            "candidate": name,
            "file_name": destination.name,
            "model_sha256": sha256(destination),
            "input_shape": contract["input_shape"],
            "output_shape": contract["output_shape"],
            "input_dtype": contract["input_dtype"],
            "output_dtype": contract["output_dtype"],
            "input_quantization": contract["input_quantization"],
            "output_quantization": contract["output_quantization"],
        })
    spec = {
        "stage": 6,
        "bundle_id": run.name,
        "sample_id": str(smoke.iloc[0].sample_id),
        "input_file": input_path.name,
        "input_sha256": sha256(input_path),
        "class_names_file": class_path.name,
        "class_names_sha256": sha256(class_path),
        "candidates": candidates,
    }
    save_json(bundle / "android_verification_spec.json", spec)
    return bundle, spec

def finalize_android(args):
    run = args.run_dir
    if run is None:
        latest = read_json(args.output_root / "06_tflite/latest.json")
        run = Path(latest["run_dir"])
    run = Path(run)
    require(run.is_dir(), f"Run Tahap 6 tidak ditemukan: {run}")
    summary_path = run / "validation_report.json"
    spec_path = run / "android_verification_bundle/stage6/android_verification_spec.json"
    require(summary_path.is_file() and spec_path.is_file(), "Run belum memiliki validasi Python/bundle Android.")
    summary = read_json(summary_path)
    spec = read_json(spec_path)
    report = read_json(args.finalize_android_report)
    require(summary.get("python_valid") is True, "Validasi Python Tahap 6 belum lulus.")
    require(report.get("stage") == 6 and report.get("bundle_id") == spec["bundle_id"], "Report Android berasal dari bundle lain.")
    require(report.get("class_names_sha256") == spec["class_names_sha256"], "class_names.json Android berbeda.")
    expected = {row["candidate"]: row for row in spec["candidates"]}
    actual = {row.get("candidate"): row for row in report.get("candidates", [])}
    require(set(actual) == set(NAMES), "Report Android tidak memuat empat kandidat lengkap.")
    for name in NAMES:
        row, exp = actual[name], expected[name]
        require(row.get("model_sha256") == exp["model_sha256"], f"Hash model Android {name} berbeda.")
        require(row.get("passed") is True, f"Pemeriksaan Android {name} gagal.")
        require(row.get("input_shape") == exp["input_shape"], f"Input shape Android {name} berbeda.")
        require(row.get("output_shape") == exp["output_shape"], f"Output shape Android {name} berbeda.")
        require(row.get("input_dtype") == exp["input_dtype"], f"Input dtype Android {name} berbeda.")
        require(row.get("output_dtype") == exp["output_dtype"], f"Output dtype Android {name} berbeda.")
        require(row.get("output_count") == 8 and row.get("finite_output") is True, f"Output Android {name} tidak valid.")
        require(row.get("label_mapping_ok") is True and row.get("interpreter_closed") is True, f"Kontrak Android {name} belum lengkap.")
    summary.update({
        "status": "complete",
        "all_valid": True,
        "android_verified": True,
        "ready_for_stage7": True,
        "android_report_path": str(Path(args.finalize_android_report)),
        "android_report_sha256": sha256(args.finalize_android_report),
        "android_verified_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    save_json(summary_path, summary)
    save_json(args.output_root / "06_tflite/latest.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

def run_python_stage(args):
    parts, _, data_report, _ = load_inputs(args.root)
    require(data_report["parent_groups_cross_split"] == 0, "Kelompok asal masih melintasi partisi.")
    if args.prepare_pool:
        require(not args.prepare_pool.exists(), "File pool sudah ada; tidak ditimpa.")
        pool = prepare_pool(args.root, parts["train"], 100, 42)
        args.prepare_pool.parent.mkdir(parents=True, exist_ok=True)
        pool.to_csv(args.prepare_pool, index=False)
        print(f"Pool metadata dibuat: {args.prepare_pool} ({len(pool)} baris).")
        return
    require(args.coverage_metadata is not None, "Gunakan --coverage-metadata dengan hasil audit GUI yang sudah ada.")
    require(args.coverage_metadata.is_file(), f"Metadata audit tidak ditemukan: {args.coverage_metadata}")
    locked = read_json(args.output_root / "05_repeat/latest.json")
    require(locked["status"] == "complete" and locked["final_fp32_locked"], "Tahap 5 belum mengunci model FP32.")
    require(locked["data_manifest_sha256"] == data_report["manifest_sha256"], "Manifest data berubah setelah Tahap 5.")
    source = Path(locked["model_path"])
    require(source.is_file() and sha256(source) == locked["model_sha256"], "Hash model FP32 berubah.")

    pool = validate_existing_audit(args.root, parts["train"], args.coverage_metadata)
    available = pool.groupby("label").group_id.nunique().reindex(CLASSES, fill_value=0)
    target_counts = available.clip(upper=50).astype(int)
    require((target_counts > 0).all(), "Ada kelas tanpa group data latih yang valid.")
    rep = final_sample(pool, 50, 42)
    rep_counts = rep.groupby("label").size().reindex(CLASSES, fill_value=0).astype(int)
    require(rep_counts.equals(target_counts), "Komposisi representative set tidak sesuai group yang tersedia.")
    require(not rep.group_id.duplicated().any(), "Representative set mengulang group asal.")
    smoke = balanced_pool(parts["validation"], 10, 4242)
    require(len(smoke) == 80 and smoke.groupby("label").size().reindex(CLASSES).eq(10).all(), "Smoke test harus 10 citra/kelas.")
    require(not smoke.group_id.duplicated().any(), "Smoke test mengulang group asal.")

    run = args.output_root / "06_tflite" / datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S_%f")
    run.mkdir(parents=True, exist_ok=False)
    rep.to_csv(run / "representative_dataset_manifest.csv", index=False)
    smoke.to_csv(run / "validation_smoke_manifest.csv", index=False)
    coverage_csv(rep, run / "representative_coverage.csv")
    metadata_completeness(rep, run / "representative_metadata_completeness.csv")
    pd.DataFrame({"label": CLASSES, "available_unique_groups": available.values, "target": target_counts.values, "selected": rep_counts.values}).to_csv(
        run / "representative_class_counts.csv", index=False
    )

    model = tf.keras.models.load_model(source, compile=False)
    require(model.input_shape == (None, 224, 224, 3) and model.output_shape == (None, 8), "Kontrak model Keras sumber berubah.")
    saved_model = run / "saved_model"
    model.export(
        saved_model,
        format="tf_saved_model",
        verbose=False,
        input_signature=[tf.TensorSpec([1, 224, 224, 3], tf.float32, name="rgb_image")],
    )
    representative_paths = rep.file_path.tolist()

    def representative():
        for relative_path in representative_paths:
            yield [image(args.root, relative_path)]

    artifacts = {}
    for name in NAMES:
        path = run / FILES[name]
        path.write_bytes(converter(saved_model, name, representative))
        require(path.is_file() and path.stat().st_size > 0, f"Artefak {name} kosong.")
        interpreter, input_detail, output_detail, contract = inspect_artifact(path, name, run / f"analyzer_{name}.txt")
        save_json(run / f"tensor_contract_{name}.json", contract)
        artifacts[name] = (path, interpreter, input_detail, output_detail, contract)

    keras_predictions = keras_predict(model, args.root, smoke)
    require(keras_predictions.shape == (80, 8) and np.isfinite(keras_predictions).all(), "Output Keras smoke tidak valid.")
    smoke_rows = smoke[["sample_id", "label", "class_index", "group_id"]].copy()
    smoke_rows["pred_keras"] = np.argmax(keras_predictions, axis=1)
    smoke_rows["confidence_keras"] = np.max(keras_predictions, axis=1)
    conversion_rows = []

    for name in NAMES:
        path, interpreter, input_detail, output_detail, contract = artifacts[name]
        predictions = np.stack([
            infer(interpreter, input_detail, output_detail, image(args.root, row.file_path))
            for row in smoke.itertuples()
        ])
        require(predictions.shape == (80, 8), f"{name}: seluruh 80 keluaran smoke tidak tersedia.")
        predicted_indices = np.argmax(predictions, axis=1)
        require(((0 <= predicted_indices) & (predicted_indices < 8)).all(), f"{name}: indeks prediksi di luar 0..7.")
        mae = float(np.mean(np.abs(keras_predictions - predictions)))
        max_abs_diff = float(np.max(np.abs(keras_predictions - predictions)))
        agreement = float(np.mean(np.argmax(keras_predictions, axis=1) == predicted_indices))
        if name == "fp32":
            print(f"[FP32 smoke] agreement={agreement:.6f}, MAE={mae:.10f}, max_abs_diff={max_abs_diff:.10f}")
            require(agreement == 1.0, f"FP32 class agreement={agreement:.6f}; harus 1.000000.")
            require(max_abs_diff <= 1e-4, f"FP32 max_abs_diff={max_abs_diff:.10f}; batas=0.0001000000.")
        smoke_rows[f"pred_{name}"] = predicted_indices
        smoke_rows[f"confidence_{name}"] = np.max(predictions, axis=1)
        conversion_rows.append({
            "candidate": name,
            "file_name": path.name,
            "model_path": str(path),
            "sha256": contract["model_sha256"],
            "size_bytes": path.stat().st_size,
            "size_mib": path.stat().st_size / 2**20,
            "input_dtype": contract["input_dtype"],
            "output_dtype": contract["output_dtype"],
            "input_scale": contract["input_quantization"][0],
            "input_zero_point": contract["input_quantization"][1],
            "output_scale": contract["output_quantization"][0],
            "output_zero_point": contract["output_quantization"][1],
            "smoke_mae_vs_keras": mae,
            "smoke_max_abs_diff": max_abs_diff,
            "smoke_class_agreement": agreement,
            "valid": True,
        })

    manifest = pd.DataFrame(conversion_rows)
    manifest.to_csv(run / "conversion_manifest.csv", index=False)
    smoke_rows.to_csv(run / "smoke_predictions.csv", index=False)
    save_json(run / "class_names.json", CLASSES)
    bundle, spec = build_android_bundle(run, artifacts, smoke, args.root)
    python_valid = bool(manifest.valid.all())
    summary = {
        "status": "python_complete",
        "stage": 6,
        "run_dir": str(run),
        "source_model_path": str(source),
        "source_model_sha256": locked["model_sha256"],
        "saved_model_sha256": tree_hash(saved_model),
        "data_manifest_sha256": data_report["manifest_sha256"],
        "coverage_metadata_sha256": sha256(args.coverage_metadata),
        "human_metadata_policy": "existing GUI audit accepted; no second manual audit required",
        "automatic_metadata_policy": "group_id and all proxies recomputed from source data at execution time",
        "representative_samples": int(len(rep)),
        "representative_target_by_class": {label: int(target_counts[label]) for label in CLASSES},
        "smoke_samples": int(len(smoke)),
        "python_valid": python_valid,
        "android_verified": False,
        "all_valid": False,
        "ready_for_stage7": False,
        "candidates": list(NAMES),
        "android_bundle_path": str(bundle),
        "android_bundle_sha256": tree_hash(bundle),
        "android_bundle_id": spec["bundle_id"],
        "tensorflow": tf.__version__,
        "smoke_runtime": "CPU batch-1; CUDA hidden; oneDNN disabled",
        "proxy_note": "brightness/orientation/scale are sampling proxies, not physical lux, exact angle, or camera distance.",
    }
    save_json(run / "validation_report.json", summary)
    save_json(args.output_root / "06_tflite/latest.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=BASE)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-pool", type=Path)
    mode.add_argument("--coverage-metadata", type=Path)
    mode.add_argument("--finalize-android-report", type=Path)
    parser.add_argument("--run-dir", type=Path, help="Run Tahap 6 yang akan difinalisasi; default memakai latest.json.")
    args = parser.parse_args()
    if args.finalize_android_report:
        require(args.finalize_android_report.is_file(), f"Report Android tidak ditemukan: {args.finalize_android_report}")
        finalize_android(args)
    else:
        run_python_stage(args)

if __name__ == "__main__":
    main()