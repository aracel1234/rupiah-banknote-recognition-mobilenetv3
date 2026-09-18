"""Bagian 2: bangun dan periksa model awal; belum melakukan pelatihan."""
import argparse
import json
from pathlib import Path

import numpy as np

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
configure_runtime, load_inputs = _dp.configure_runtime, _dp.load_inputs
require, save_json, sha256 = _dp.require, _dp.save_json, _dp.sha256

def build_model(seed=42, learning_rate=3e-4):
    tf = configure_runtime(seed)
    L = tf.keras.layers
    backbone = tf.keras.applications.MobileNetV3Small(
        input_shape=IMAGE_SHAPE, alpha=1.0, minimalistic=False,
        include_top=False, weights="imagenet", include_preprocessing=True,
        name="backbone",
    )
    backbone.trainable = False
    inputs = tf.keras.Input(shape=IMAGE_SHAPE, dtype="float32", name="rgb_image")
    x = backbone(inputs, training=False)
    x = L.GlobalAveragePooling2D(name="global_average_pool")(x)
    x = L.Dropout(0.20, seed=seed + 7, name="head_dropout")(x)
    outputs = L.Dense(len(CLASSES), activation="softmax", dtype="float32", name="scores")(x)
    model = tf.keras.Model(inputs, outputs, name="rupiah_mobilenetv3_small")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate, beta_1=0.9, beta_2=0.999, epsilon=1e-7),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy")],
    )
    return model, backbone

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("/home/aracel/Downloads/Skripsi/pengembangan_model/02_model"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    _, _, data_report, _ = load_inputs(args.root)
    model, backbone = build_model(args.seed)
    import tensorflow as tf
    require(model.input_shape == (None, *IMAGE_SHAPE), "Bentuk masukan tidak sesuai.")
    require(model.output_shape == (None, 8), "Bentuk keluaran tidak sesuai.")
    require(model.inputs[0].dtype == "float32" and model.outputs[0].dtype == "float32",
            "Antarmuka model bukan FP32.")
    require(not backbone.trainable_weights, "Backbone belum beku.")
    rescaling = [l for l in backbone.layers if isinstance(l, tf.keras.layers.Rescaling)]
    require(len(rescaling) == 1, "Harus ada tepat satu Rescaling internal.")
    require(np.isclose(rescaling[0].scale, 1 / 127.5) and rescaling[0].offset == -1,
            "Rumus Rescaling tidak sesuai kontrak.")
    require(all(w.dtype == "float32" for w in model.weights), "Bobot model bukan FP32.")
    args.out.mkdir(parents=True, exist_ok=True)
    probe = tf.random.stateless_uniform((2, *IMAGE_SHAPE), [args.seed, 0], maxval=255)
    before = model(probe, training=False).numpy()
    require(np.isfinite(before).all() and (before >= 0).all(), "Skor model tidak valid.")
    require(np.allclose(before.sum(axis=1), 1, atol=1e-6, rtol=0), "Jumlah Softmax bukan satu.")
    path = args.out / "initial_model.keras"
    model.save(path)
    restored = tf.keras.models.load_model(path, compile=False)
    after = restored(probe, training=False).numpy()
    delta = float(np.max(np.abs(before - after)))
    require(delta <= 1e-6, "Prediksi berubah setelah simpan/muat ulang.")
    lines = []
    model.summary(print_fn=lambda line: lines.append(line), expand_nested=True)
    (args.out / "model_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    save_json(args.out / "class_names.json", CLASSES)
    save_json(args.out / "tensor_contract.json", {
        "scope": "initial_keras_fp32", "input_shape": [None, 224, 224, 3],
        "android_input_shape_target": [1, 224, 224, 3], "layout": "NHWC",
        "color": "RGB", "input_dtype": "float32", "external_range": [0, 255],
        "resize": "bilinear", "antialias": False, "preserve_aspect_ratio": False,
        "internal_preprocessing": "x / 127.5 - 1", "output_shape": [None, 8],
        "output_dtype": "float32", "output_semantics": "softmax_probabilities",
        "apply_softmax_again": False, "class_names": CLASSES,
    })
    report = {"status": "initialized_not_trained", "seed": args.seed,
              "tensorflow": tf.__version__, "keras": tf.keras.__version__,
              "parameters_total": model.count_params(),
              "parameters_trainable": int(sum(np.prod(w.shape) for w in model.trainable_weights)),
              "backbone_layers": len(backbone.layers), "reload_max_abs_diff": delta,
              "model_sha256": sha256(path), "data_manifest_sha256": data_report["manifest_sha256"],
              "parent_groups_cross_split": data_report["parent_groups_cross_split"]}
    save_json(args.out / "model_check.json", report)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
