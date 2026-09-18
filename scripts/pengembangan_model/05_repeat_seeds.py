"""Bagian 5: ulangi konfigurasi terpilih pada seed 42, 123, 2026 dan kunci model FP32."""
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf

BASE = Path("/home/aracel/Downloads/Skripsi/pengembangan_model")
SEEDS = (42, 123, 2026)

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
_bm = _load_local("build_model", "02_build_model.py")
_th = _load_local("train_head", "03_train_head.py")
CLASSES, DEFAULT_ROOT, IMAGE_SHAPE = _dp.CLASSES, _dp.DEFAULT_ROOT, _dp.IMAGE_SHAPE
load_inputs, make_dataset, require = _dp.load_inputs, _dp.make_dataset, _dp.require
save_json, sha256 = _dp.save_json, _dp.sha256
build_model = _bm.build_model
DELTA, MacroF1, choose = _th.DELTA, _th.MacroF1, _th.choose
frozen_hashes, plot_history, read_json = _th.frozen_hashes, _th.plot_history, _th.read_json

def backbone_hash(model):
    h = hashlib.sha256()
    for w in model.get_layer("backbone").weights:
        h.update(w.numpy().tobytes())
    return h.hexdigest()

def set_trainable(model, fraction):
    model.trainable = True
    backbone = model.get_layer("backbone")
    backbone.trainable = fraction > 0
    n = math.ceil(len(backbone.layers) * fraction)
    for i, layer in enumerate(backbone.layers):
        layer.trainable = fraction > 0 and i >= len(backbone.layers) - n and not isinstance(
            layer, tf.keras.layers.BatchNormalization)
    actual = sum(bool(layer.trainable_weights) for layer in backbone.layers)
    return n, actual, int(sum(np.prod(w.shape) for w in model.trainable_weights))

class ResumeCandidates(tf.keras.callbacks.Callback):
    def __init__(self, folder, config):
        super().__init__()
        self.folder, self.config = folder, config
        self.path = folder / "checkpoint_candidates.json"
        self.records = read_json(self.path) if self.path.exists() else []

    def on_train_batch_end(self, batch, logs=None):
        require(np.isfinite((logs or {}).get("loss", np.nan)), "Loss tidak valid.")

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        require(all(np.isfinite(logs[k]) for k in ("loss", "val_loss", "val_macro_f1")), "Metrik tidak valid.")
        e = epoch + 1
        self.records = [r for r in self.records if r["epoch"] != e]
        row = dict(self.config, epoch=e, val_loss=float(logs["val_loss"]),
                   val_macro_f1=float(logs["val_macro_f1"]), val_accuracy=float(logs["val_accuracy"]),
                   learning_rate=float(tf.keras.backend.get_value(self.model.optimizer.learning_rate)))
        maximum = max([row["val_macro_f1"]] + [r["val_macro_f1"] for r in self.records])
        if maximum - row["val_macro_f1"] < DELTA - 1e-12:
            row["weights_path"] = str(self.folder / f"epoch_{e:02d}.weights.h5")
            self.model.save_weights(row["weights_path"])
            self.records.append(row)
        keep = [r for r in self.records if maximum - r["val_macro_f1"] < DELTA - 1e-12]
        for r in self.records:
            if r not in keep:
                Path(r["weights_path"]).unlink(missing_ok=True)
        self.records = keep
        save_json(self.path, keep)

def compile_model(model, lr):
    model.compile(
        optimizer=tf.keras.optimizers.Adam(lr, beta_1=0.9, beta_2=0.999, epsilon=1e-7),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(),
        metrics=[tf.keras.metrics.SparseCategoricalAccuracy(name="accuracy"), MacroF1()],
        jit_compile=False,
    )

def run_phase(root, parts, weights, model, folder, seed, batch, lr, fraction, epochs, trial):
    folder.mkdir(parents=True, exist_ok=True)
    top, actual, params = set_trainable(model, fraction)
    config = dict(trial=trial, seed=seed, batch_size=batch, learning_rate=lr, fraction=fraction,
                  epochs=epochs, top_layers=top, backbone_layers=len(model.get_layer("backbone").layers),
                  trainable_backbone_layers=actual, trainable_parameters=params)
    cfg = folder / "config.json"
    if cfg.exists():
        require(read_json(cfg) == config, f"Konfigurasi lama berbeda: {folder}")
    else:
        save_json(cfg, config)
    frozen = frozen_hashes(model)
    compile_model(model, lr)
    train = make_dataset(root, parts["train"], batch, True, seed)
    val = make_dataset(root, parts["validation"], batch, False, seed)
    ckpt = ResumeCandidates(folder, config)
    callbacks = [tf.keras.callbacks.BackupAndRestore(str(folder / "backup"), save_freq="epoch", delete_checkpoint=False),
                 ckpt,
                 tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", mode="min", factor=0.2,
                                                      patience=3, min_delta=1e-4, min_lr=1e-7),
                 tf.keras.callbacks.EarlyStopping(monitor="val_macro_f1", mode="max", patience=6,
                                                  min_delta=DELTA, restore_best_weights=False),
                 tf.keras.callbacks.CSVLogger(str(folder / "history.csv"), append=True)]
    model.fit(train, validation_data=val, epochs=epochs, class_weight=weights,
              callbacks=callbacks, verbose=2, shuffle=False)
    require(frozen == frozen_hashes(model), "Bobot yang seharusnya beku berubah.")
    require(bool(ckpt.records), "Checkpoint kandidat tidak ditemukan.")
    history = pd.read_csv(folder / "history.csv").drop_duplicates("epoch", keep="last").sort_values("epoch")
    history.to_csv(folder / "history.csv", index=False)
    plot_history(folder)
    selected = choose(ckpt.records)
    model.load_weights(selected["weights_path"])
    path = folder / "best.keras"
    model.save(path)
    return dict(selected, model_path=str(path), model_sha256=sha256(path))

def validate_final(path):
    model = tf.keras.models.load_model(path, compile=False)
    require(model.input_shape == (None, *IMAGE_SHAPE) and model.output_shape == (None, 8), "Bentuk model final salah.")
    require(str(model.inputs[0].dtype) == "float32" and str(model.outputs[0].dtype) == "float32", "Dtype model final salah.")
    require(model.count_params() == 943736, "Jumlah parameter model final berubah.")
    require(not any(type(l).__name__.startswith("Random") for l in model.layers), "Augmentasi masuk ke graf model.")
    scales = [l for l in model.get_layer("backbone").layers if isinstance(l, tf.keras.layers.Rescaling)]
    require(len(scales) == 1 and np.isclose(scales[0].scale, 1 / 127.5) and scales[0].offset == -1, "Rescaling final salah.")
    probe = tf.random.stateless_uniform((2, *IMAGE_SHAPE), [42, 5], maxval=255)
    p = model(probe, training=False).numpy()
    require(np.isfinite(p).all() and np.allclose(p.sum(1), 1, atol=1e-6), "Keluaran model final tidak valid.")
    return model

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--output-root", type=Path, default=BASE)
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()
    parts, weights, report, _ = load_inputs(args.root)
    require(report["parent_groups_cross_split"] == 0, "Kelompok gambar asal masih lintas partisi.")
    head = read_json(args.output_root / "03_head/latest.json")
    fine = read_json(args.output_root / "04_finetune/latest.json")
    require(head["status"] == fine["status"] == "complete" and head["stage"] == 3 and fine["stage"] == 4, "Tahap 3/4 belum lengkap.")
    require(head["completed_trials"] == 4 and fine["completed_trials"] == 6 and head["seed"] == fine["seed"] == 42, "Jumlah trial/seed tahap 3-4 tidak sesuai.")
    require(head["data_manifest_sha256"] == fine["data_manifest_sha256"] == report["manifest_sha256"], "Manifest tahap 3/4 berbeda.")
    require(sha256(head["model_path"]) == head["model_sha256"] and fine["head_model_sha256"] == head["model_sha256"], "Identitas model kepala tahap 3/4 tidak konsisten.")
    require(sha256(fine["model_path"]) == fine["model_sha256"], "Artefak hasil tahap 4 berubah.")
    initial = args.output_root / "02_model/initial_model.keras"
    require(head["initial_model_sha256"] == sha256(initial), "Model awal tahap 3 berubah.")
    initial_model = tf.keras.models.load_model(initial, compile=False)
    pretrained_hash = backbone_hash(initial_model)
    if args.check_only:
        print(json.dumps({"status": "check_passed", "seeds": list(SEEDS), "head_selected": head["selected"],
                          "fine_tuning_accepted": fine["fine_tuning_accepted"], "fine_selected": fine["selected"]},
                         indent=2, ensure_ascii=False))
        return
    out = args.output_root / "05_repeat"
    out.mkdir(parents=True, exist_ok=True)
    signature = hashlib.sha256(json.dumps({"head": head["selected"], "fine": fine["selected"], "accepted": fine["fine_tuning_accepted"]}, sort_keys=True, default=str).encode()).hexdigest()
    results = []
    for seed in SEEDS:
        seed_dir = out / f"seed_{seed}"
        done = seed_dir / "complete.json"
        if done.exists():
            record = read_json(done)
            require(record.get("search_signature") == signature, f"Konfigurasi pencarian berubah untuk seed {seed}.")
            require(sha256(record["model_path"]) == record["model_sha256"], f"Model seed {seed} berubah.")
            results.append(record)
            continue
        tf.keras.backend.clear_session()
        model, _ = build_model(seed)
        require(backbone_hash(model) == pretrained_hash, "Bobot backbone ImageNet berbeda dari model awal tahap 2.")
        h = head["selected"]
        head_record = run_phase(args.root, parts, weights, model, seed_dir / "head", seed,
                                int(h["batch_size"]), float(h["learning_rate"]), 0.0, 30, f"head_seed{seed}")
        final = head_record
        if fine["fine_tuning_accepted"]:
            model = tf.keras.models.load_model(head_record["model_path"], compile=False)
            f = fine["selected"]
            final = run_phase(args.root, parts, weights, model, seed_dir / "finetune", seed,
                              int(h["batch_size"]), float(f["learning_rate"]), float(f["fraction"]), 20,
                              f"finetune_seed{seed}")
        final.update(seed=seed, head_model_sha256=head_record["model_sha256"], fine_tuning_accepted=bool(fine["fine_tuning_accepted"]), search_signature=signature)
        save_json(done, final)
        results.append(final)
    table = pd.DataFrame(results).sort_values("seed")
    table.to_csv(out / "repeat_results.csv", index=False)
    selected = choose(results)
    final_path = out / "mobilenetv3small_fp32_best.keras"
    shutil.copy2(selected["model_path"], final_path)
    model = validate_final(final_path)
    lines = []
    model.summary(print_fn=lines.append, expand_nested=True)
    (out / "model_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    save_json(out / "class_names.json", CLASSES)
    contract = read_json(args.output_root / "02_model/tensor_contract.json")
    contract.update(scope="locked_keras_fp32", model_sha256=sha256(final_path), selected_seed=int(selected["seed"]))
    save_json(out / "tensor_contract.json", contract)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(table["seed"].astype(str), table["val_macro_f1"])
    mean = float(table["val_macro_f1"].mean())
    ax.axhline(mean, linestyle="--", label=f"Mean = {mean:.4f}")
    ax.set(xlabel="Seed", ylabel="Validation Macro F1", title="Pengulangan Konfigurasi Terpilih")
    ax.legend(); fig.tight_layout(); fig.savefig(out / "seed_repeat_macro_f1.png", dpi=180); plt.close(fig)
    summary = {"status": "complete", "stage": 5, "seeds": list(SEEDS), "completed_runs": 3,
               "macro_f1_mean": mean, "macro_f1_std": float(table["val_macro_f1"].std(ddof=1)),
               "selected": selected, "model_path": str(final_path), "model_sha256": sha256(final_path),
               "data_manifest_sha256": report["manifest_sha256"], "final_fp32_locked": True,
               "fine_tuning_accepted": bool(fine["fine_tuning_accepted"])}
    save_json(out / "selection.json", summary)
    save_json(out / "latest.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()