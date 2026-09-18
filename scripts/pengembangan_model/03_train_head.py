"""Bagian 3: empat konfigurasi pelatihan kepala; fungsi bersama bagian 4."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf

BASE = Path("/home/aracel/Downloads/Skripsi/pengembangan_model")
SEED, DELTA = 42, 0.001

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
configure_runtime, load_inputs, make_dataset = _dp.configure_runtime, _dp.load_inputs, _dp.make_dataset
require, save_json, sha256 = _dp.require, _dp.save_json, _dp.sha256

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def checked_inputs(root, output_root):
    parts, weights, report, _ = load_inputs(root)
    require(report["parent_groups_cross_split"] == 0, "Jalankan 05c baru: gambar asal masih lintas partisi.")
    data = read_json(output_root / "01_data/data_check.json")
    model = read_json(output_root / "02_model/model_check.json")
    hashes = report["manifest_sha256"]
    require(data["metadata_valid"] and data["manifest_sha256"] == hashes,
            "Laporan data lama; jalankan ulang 01_data_pipeline.py.")
    require(data["parent_groups_cross_split"] == model["parent_groups_cross_split"] == 0,
            "Laporan bagian 1/2 masih mencatat kelompok lintas partisi.")
    require(model["data_manifest_sha256"] == hashes, "Model merujuk partisi lama; jalankan 02_build_model.py.")
    require(model["status"] == "initialized_not_trained" and model["seed"] == SEED,
            "Diperlukan model awal bagian 2 dengan seed 42.")
    initial = output_root / "02_model/initial_model.keras"
    require(sha256(initial) == model["model_sha256"], "Hash model awal tidak sesuai laporan.")
    require(read_json(output_root / "02_model/class_names.json") == CLASSES, "Urutan kelas model berubah.")
    return parts, weights, report, initial

@tf.keras.utils.register_keras_serializable(package="Rupiah")
class MacroF1(tf.keras.metrics.Metric):
    def __init__(self, name="macro_f1", **kwargs):
        super().__init__(name=name, **kwargs)
        self.cm = self.add_weight(name="confusion", shape=(8, 8), initializer="zeros", dtype="float64")

    def update_state(self, y_true, y_pred, sample_weight=None):
        truth = tf.cast(tf.reshape(y_true, [-1]), tf.int32)
        pred = tf.argmax(y_pred, axis=-1, output_type=tf.int32)
        self.cm.assign_add(tf.math.confusion_matrix(truth, pred, num_classes=8, dtype=tf.float64))

    def result(self):
        denominator = tf.reduce_sum(self.cm, axis=0) + tf.reduce_sum(self.cm, axis=1)
        return tf.reduce_mean(tf.math.divide_no_nan(2 * tf.linalg.diag_part(self.cm), denominator))

    def reset_state(self):
        self.cm.assign(tf.zeros_like(self.cm))

def choose(records):
    require(bool(records), "Tidak ada checkpoint yang dapat dipilih.")
    maximum = max(r["val_macro_f1"] for r in records)
    close = [r for r in records if maximum - r["val_macro_f1"] < DELTA - 1e-12]
    return min(close, key=lambda r: (r["val_loss"], r["trainable_backbone_layers"], r["epoch"], r["trial"]))

class Checkpoints(tf.keras.callbacks.ModelCheckpoint):
    def __init__(self, folder, config):
        super().__init__(folder / "best_f1.weights.h5", monitor="val_macro_f1", mode="max",
                         save_best_only=True, save_weights_only=True)
        self.folder, self.config, self.records = folder, config, []

    def on_train_batch_end(self, batch, logs=None):
        require(np.isfinite((logs or {}).get("loss", np.nan)), "Loss tidak valid; eksperimen dihentikan.")

    def on_epoch_end(self, epoch, logs=None):
        logs = logs if logs is not None else {}
        require(all(np.isfinite(logs[k]) for k in ["loss", "val_loss", "val_macro_f1"]),
                "Metrik tidak valid; checkpoint tidak diterbitkan.")
        logs["learning_rate"] = float(tf.keras.backend.get_value(self.model.optimizer.learning_rate))
        super().on_epoch_end(epoch, logs)
        row = dict(self.config, epoch=epoch + 1, val_loss=float(logs["val_loss"]),
                   val_macro_f1=float(logs["val_macro_f1"]), val_accuracy=float(logs["val_accuracy"]))
        row["weights_path"] = str(self.folder / f"epoch_{epoch + 1:02d}.weights.h5")
        maximum = max([row["val_macro_f1"]] + [r["val_macro_f1"] for r in self.records])
        if maximum - row["val_macro_f1"] < DELTA - 1e-12:
            self.model.save_weights(row["weights_path"])
            self.records.append(row)
        keep = [r for r in self.records if maximum - r["val_macro_f1"] < DELTA - 1e-12]
        for old in self.records:
            if old not in keep:
                Path(old["weights_path"]).unlink()
        self.records = keep
        save_json(self.folder / "checkpoint_candidates.json", keep)

def prepare_model(source, fraction=0.0):
    tf.keras.backend.clear_session()
    configure_runtime(SEED)
    model = tf.keras.models.load_model(source, compile=False)
    require(model.input_shape == (None, *IMAGE_SHAPE) and model.output_shape == (None, 8),
            "Kontrak bentuk model berubah.")
    require(model.count_params() == 943736 and all(w.dtype == "float32" for w in model.weights),
            "Arsitektur atau tipe bobot model berubah.")
    backbone = model.get_layer("backbone")
    scales = [l for l in backbone.layers if isinstance(l, tf.keras.layers.Rescaling)]
    require(len(scales) == 1 and np.isclose(scales[0].scale, 1 / 127.5) and scales[0].offset == -1,
            "Rescaling internal tidak sesuai.")
    require(model.get_layer("scores").activation == tf.keras.activations.softmax,
            "Keluaran model harus Softmax.")
    model.trainable = True
    backbone.trainable = fraction > 0
    count = math.ceil(len(backbone.layers) * fraction)
    for i, layer in enumerate(backbone.layers):
        layer.trainable = fraction > 0 and i >= len(backbone.layers) - count and not isinstance(
            layer, tf.keras.layers.BatchNormalization)
    actual = sum(bool(l.trainable_weights) for l in backbone.layers)
    require(actual > 0 if fraction else not backbone.trainable_weights, "Pengaturan backbone gagal.")
    return model, {"top_layers": count, "backbone_layers": len(backbone.layers),
                   "trainable_backbone_layers": actual,
                   "trainable_parameters": int(sum(np.prod(w.shape) for w in model.trainable_weights))}

def frozen_hashes(model):
    return {w.path: hashlib.sha256(w.numpy().tobytes()).hexdigest() for w in model.non_trainable_weights}

def plot_history(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    history = pd.read_csv(path / "history.csv")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))
    for ax, metric in zip(axes, ["loss", "accuracy", "macro_f1"]):
        ax.plot(history.epoch + 1, history[metric], label="Latih", marker="o", markersize=3)
        ax.plot(history.epoch + 1, history[f"val_{metric}"], label="Validasi", marker="o", markersize=3)
        ax.set(xlabel="Epoch", ylabel=metric)
        ax.grid(alpha=0.2)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path / "learning_curves.png", dpi=160)
    plt.close(fig)

def train_trial(root, parts, weights, source, folder, config):
    folder.mkdir(parents=True, exist_ok=False)
    model, details = prepare_model(source, config["fraction"])
    config = dict(config, **details, source_sha256=sha256(source), seed=SEED)
    save_json(folder / "config.json", config)
    save_json(folder / "layers.json", [{"index": i, "name": l.name, "type": type(l).__name__,
               "trainable": l.trainable, "has_trainable_weights": bool(l.trainable_weights)}
               for i, l in enumerate(model.get_layer("backbone").layers)])
    frozen = frozen_hashes(model)
    model.compile(optimizer=tf.keras.optimizers.Adam(config["learning_rate"], beta_1=0.9, beta_2=0.999,
                  epsilon=1e-7), loss=tf.keras.losses.SparseCategoricalCrossentropy(),
                  metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy"), MacroF1()],
                  jit_compile=False)
    train = make_dataset(root, parts["train"], config["batch_size"], training=True, seed=SEED)
    validation = make_dataset(root, parts["validation"], config["batch_size"], training=False, seed=SEED)
    checkpoints = Checkpoints(folder, config)
    callbacks = [tf.keras.callbacks.TerminateOnNaN(), checkpoints,
                 tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", mode="min", factor=0.2,
                                                    patience=3, min_delta=1e-4, min_lr=1e-7),
                 tf.keras.callbacks.EarlyStopping(monitor="val_macro_f1", mode="max", patience=6,
                                                 min_delta=DELTA, restore_best_weights=False),
                 tf.keras.callbacks.CSVLogger(str(folder / "history.csv"))]
    model.fit(train, validation_data=validation, epochs=config["epochs"], class_weight=weights,
              callbacks=callbacks, verbose=2, shuffle=False)
    require(frozen == frozen_hashes(model), "Bobot yang seharusnya beku berubah.")
    require(bool(checkpoints.records), "Tidak ada checkpoint yang tersimpan.")
    plot_history(folder)
    save_json(folder / "trial_check.json", {"frozen_weights_unchanged": True,
              "validation_samples_per_epoch": len(parts["validation"]), "test_images_used": 0})
    return checkpoints.records

def save_selected(source, record, destination):
    model, details = prepare_model(source, record["fraction"])
    if record.get("weights_path"):
        model.load_weights(record["weights_path"])
    probe = tf.random.stateless_uniform((2, *IMAGE_SHAPE), [SEED, 0], maxval=255)
    before = model(probe, training=False).numpy()
    require(np.isfinite(before).all() and np.allclose(before.sum(axis=1), 1, atol=1e-6, rtol=0),
            "Probabilitas checkpoint tidak valid.")
    require(all(np.isfinite(w.numpy()).all() for w in model.weights), "Bobot checkpoint tidak valid.")
    model.save(destination)
    restored = tf.keras.models.load_model(destination, compile=False)
    difference = float(np.max(np.abs(before - restored(probe, training=False).numpy())))
    require(difference <= 1e-6, "Prediksi berubah setelah simpan-muat.")
    return {"model_path": str(destination), "model_sha256": sha256(destination),
            "reload_max_abs_diff": difference, **details}

def new_run(output_root, stage):
    path = output_root / stage / datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S_%f")
    path.mkdir(parents=True, exist_ok=False)
    return path

def publish(run, summary, records):
    pd.DataFrame(records).to_csv(run / "candidate_results.csv", index=False)
    summary = dict(summary, status="complete", seed=SEED, tensorflow=tf.__version__, keras=tf.keras.__version__)
    save_json(run / "selection.json", summary)
    save_json(run / "class_names.json", CLASSES)
    temporary = run.parent / ".latest.tmp"
    save_json(temporary, summary)
    temporary.replace(run.parent / "latest.json")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=BASE)
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()

def main():
    args = arguments(__doc__)
    parts, weights, report, source = checked_inputs(args.root, args.output_root)
    prepare_model(source)
    if args.check_only:
        print("Pemeriksaan bagian 3 lulus; pelatihan belum dijalankan.")
        return
    run = new_run(args.output_root, "03_head")
    records = []
    for batch in [16, 32]:
        for rate in [3e-4, 1e-3]:
            trial = f"b{batch}_lr{rate:.0e}"
            config = dict(trial=trial, batch_size=batch, learning_rate=rate, fraction=0.0, epochs=30)
            records.extend(train_trial(args.root, parts, weights, source, run / trial, config))
    selected = choose(records)
    artifact = save_selected(source, selected, run / "best_head.keras")
    publish(run, {"stage": 3, "completed_trials": 4, "selected": selected, **artifact,
                 "data_manifest_sha256": report["manifest_sha256"],
                 "initial_model_sha256": sha256(source), "final_fp32_locked": False}, records)

if __name__ == "__main__":
    main()
