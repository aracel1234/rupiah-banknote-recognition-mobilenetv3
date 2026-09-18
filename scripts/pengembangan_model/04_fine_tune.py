"""Bagian 4: enam konfigurasi fine-tuning dan pembandingan dengan fase 1."""
from pathlib import Path

def _load_local(alias, filename):
    import importlib.util, sys
    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(alias, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module

_th = _load_local("train_head", "03_train_head.py")
DELTA, SEED = _th.DELTA, _th.SEED
arguments, checked_inputs, choose, new_run = _th.arguments, _th.checked_inputs, _th.choose, _th.new_run
prepare_model, publish, read_json = _th.prepare_model, _th.publish, _th.read_json
require, save_selected, sha256, train_trial = _th.require, _th.save_selected, _th.sha256, _th.train_trial

def eligible_fine_tuning(records, baseline):
    return [r for r in records if r["val_macro_f1"] - baseline["val_macro_f1"] >= DELTA - 1e-12]

def main():
    args = arguments(__doc__)
    parts, weights, report, initial = checked_inputs(args.root, args.output_root)
    head = read_json(args.output_root / "03_head/latest.json")
    require(head["status"] == "complete" and head["stage"] == 3 and head["completed_trials"] == 4,
            "Empat konfigurasi fase 1 belum selesai.")
    require(head["seed"] == SEED and head["data_manifest_sha256"] == report["manifest_sha256"],
            "Seed/partisi fase 1 berbeda dari konfigurasi saat ini.")
    require(head["initial_model_sha256"] == sha256(initial), "Model awal telah berubah setelah fase 1.")
    source = head["model_path"]
    require(sha256(source) == head["model_sha256"], "Hash checkpoint kepala berubah.")
    prepare_model(source)
    if args.check_only:
        print("Pemeriksaan bagian 4 lulus; fine-tuning belum dijalankan.")
        return
    run = new_run(args.output_root, "04_finetune")
    baseline, records = head["selected"], []
    for fraction in [0.20, 0.35, 0.50]:
        for rate in [1e-5, 3e-5]:
            trial = f"p{round(fraction * 100)}_lr{rate:.0e}"
            config = dict(trial=trial, batch_size=baseline["batch_size"], learning_rate=rate,
                          fraction=fraction, epochs=20)
            records.extend(train_trial(args.root, parts, weights, source, run / trial, config))
    eligible = eligible_fine_tuning(records, baseline)
    selected = choose(eligible) if eligible else dict(baseline, weights_path=None)
    artifact = save_selected(source, selected, run / "best_search.keras")
    publish(run, {"stage": 4, "completed_trials": 6, "selected": selected, **artifact,
                 "fine_tuning_accepted": bool(eligible), "baseline": baseline,
                 "macro_f1_gain": selected["val_macro_f1"] - baseline["val_macro_f1"],
                 "data_manifest_sha256": report["manifest_sha256"],
                 "head_model_sha256": sha256(source), "final_fp32_locked": False,
                 "next_step": "Ulangi konfigurasi terpilih dengan seed 42, 123, 2026 pada bagian 5."}, records)

if __name__ == "__main__":
    main()