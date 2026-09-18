"""Validasi bukti benchmark Android dan seleksi leksikografis Tahap 7."""
import hashlib
from itertools import combinations
from pathlib import Path

import numpy as np

CHECKS = [
    "five_independent_process_sessions", "paired_session_order", "warmup_30", "stable_500",
    "timer_interpreter_run_only", "inputs_preprocessed", "battery_50_80_no_charging",
    "airplane_mode", "brightness_50", "power_saver_off", "idle_5_minutes",
    "pss_separate_sessions", "pss_baseline_wait_10s", "pss_baseline_5_every_2s",
    "pss_warmup_20", "pss_active_15_every_2s", "android_smoke_passed",
]

def require(ok, message):
    if not ok:
        raise ValueError(message)

def tree_hash(folder):
    digest = hashlib.sha256()
    folder = Path(folder)
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(folder)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()

def protocol_template(manifest, android_bundle_sha256):
    return {
        "runtime": {
            "device": "POCO X5 Pro 5G",
            "execution": "CPU_XNNPACK",
            "threads": 4,
            "gpu": False,
            "nnapi": False,
            "npu": False,
            "build": "release",
            "android_version": "",
            "tflite_version": "",
        },
        "android_bundle_sha256": android_bundle_sha256,
        "model_sha256": dict(zip(manifest.candidate, manifest.sha256)),
        "latency_csv_sha256": "",
        "memory_csv_sha256": "",
        "evidence_directory": "",
        "checks": {k: False for k in CHECKS},
    }

def validate_benchmark(lat, mem, manifest):
    hashes = dict(zip(manifest.candidate, manifest.sha256))
    for frame, value, keys in (
        (lat, "time_ms", ["candidate", "session", "measurement_type", "index"]),
        (mem, "total_pss_kb", ["candidate", "session", "phase", "snapshot"]),
    ):
        require(set(frame.candidate) == set(hashes), "Kandidat benchmark tidak lengkap.")
        values = frame[value].to_numpy(float)
        require(np.isfinite(values).all() and (values > 0).all(), "Pengukuran harus positif dan finite.")
        require(not frame.duplicated(keys).any(), "Pengukuran ganda ditemukan.")
        for name, digest in hashes.items():
            d = frame[frame.candidate.eq(name)]
            require(d.model_sha256.eq(digest).all() and set(d.session) == set(range(1, 6)), "Hash/sesi salah.")
    require(set(lat.measurement_type) == {"initialization", "first_inference", "stable"}, "Jenis latensi salah.")
    require(set(mem.phase) == {"baseline", "active"}, "Fase memori salah.")
    for name in hashes:
        for session in range(1, 6):
            d = lat[lat.candidate.eq(name) & lat.session.eq(session)]
            for kind, count in (("initialization", 1), ("first_inference", 1), ("stable", 500)):
                z = d[d.measurement_type.eq(kind)].sort_values("index")
                require(len(z) == count and z["index"].tolist() == list(range(1, count + 1)), "Indeks/sesi latensi tidak lengkap.")
                if kind == "stable":
                    require(np.array_equal(z.tensor_index.to_numpy(), np.arange(500) % 80), "Urutan tensor berbeda.")
            d = mem[mem.candidate.eq(name) & mem.session.eq(session)]
            for phase, count in (("baseline", 5), ("active", 15)):
                z = d[d.phase.eq(phase)]
                require(len(z) == count and set(z.snapshot) == set(range(1, count + 1)), "Indeks PSS tidak lengkap.")

def validate_protocol(p, manifest, latency_path, memory_path, bundle_path, expected_bundle_sha256):
    expected = {
        "device": "POCO X5 Pro 5G", "execution": "CPU_XNNPACK", "threads": 4,
        "gpu": False, "nnapi": False, "npu": False, "build": "release",
    }
    require(all(p.get("runtime", {}).get(k) == v for k, v in expected.items()), "Runtime benchmark tidak sesuai skripsi.")
    require(bool(p["runtime"].get("android_version")) and bool(p["runtime"].get("tflite_version")), "Catat versi Android dan runtime.")
    require(p.get("android_bundle_sha256") == expected_bundle_sha256, "Identitas bundle benchmark salah.")
    require(tree_hash(bundle_path) == expected_bundle_sha256, "Isi bundle benchmark berubah.")
    require(p.get("model_sha256") == dict(zip(manifest.candidate, manifest.sha256)), "Identitas model protokol salah.")
    for key, path in (("latency_csv_sha256", latency_path), ("memory_csv_sha256", memory_path)):
        require(p.get(key) == hashlib.sha256(Path(path).read_bytes()).hexdigest(), "CSV berbeda dari catatan protokol.")
    require(all(p.get("checks", {}).get(k) is True for k in CHECKS), "Catatan pelaksanaan/smoke Android belum lengkap.")
    require(bool(p.get("evidence_directory")), "Cantumkan lokasi bukti kondisi perangkat/log mentah.")

def select_with_uncertainty(table, lat, mem, iterations=2000):
    """Bootstrap blok sesi berpasangan untuk median, P95, dan tambahan PSS."""
    names = sorted(table.candidate)
    timings, pss = {}, {}
    for name in names:
        d = lat[lat.candidate.eq(name) & lat.measurement_type.eq("stable")]
        timings[name] = d.sort_values(["session", "index"]).time_ms.to_numpy().reshape(5, 500)
        d = mem[mem.candidate.eq(name)]
        pss[name] = np.array([
            d[d.session.eq(s) & d.phase.eq("active")].total_pss_kb.median()
            - d[d.session.eq(s) & d.phase.eq("baseline")].total_pss_kb.median()
            for s in range(1, 6)
        ]) / 1024
    rng = np.random.default_rng(42)
    draws = rng.integers(0, 5, size=(iterations, 5))
    values = {}
    for name in names:
        sampled = timings[name][draws].reshape(iterations, -1)
        values[name] = {
            "median_ms": np.median(sampled, axis=1),
            "p95_ms": np.percentile(sampled, 95, axis=1),
            "additional_total_pss_mb": np.median(pss[name][draws], axis=1),
        }
    pairs = []
    for a, b in combinations(names, 2):
        for metric in ("median_ms", "p95_ms", "additional_total_pss_mb"):
            lo, hi = np.percentile(values[a][metric] - values[b][metric], [2.5, 97.5])
            pairs.append({"a": a, "b": b, "metric": metric, "ci_low": float(lo), "ci_high": float(hi)})
    current, steps = table.copy(), []
    for metric in ("median_ms", "p95_ms", "size_bytes", "additional_total_pss_mb"):
        before = sorted(current.candidate)
        if metric == "size_bytes":
            current = current[current[metric].eq(current[metric].min())]
        else:
            eliminated = set()
            for row in pairs:
                if row["metric"] != metric or row["a"] not in before or row["b"] not in before:
                    continue
                if row["ci_high"] < 0:
                    eliminated.add(row["b"])
                if row["ci_low"] > 0:
                    eliminated.add(row["a"])
            survivors = current[~current.candidate.isin(eliminated)]
            require(len(survivors) > 0, "Perbandingan tidak konsisten; periksa benchmark.")
            current = survivors
        steps.append({"metric": metric, "before": before, "after": sorted(current.candidate)})
        if len(current) == 1:
            break
    require(len(current) == 1, "Kandidat tetap seri pada seluruh kriteria; laporkan seri dan jangan memilih diam-diam.")
    return current.iloc[0].to_dict(), {
        "iterations": iterations, "seed": 42, "resampling_unit": "paired_session_block",
        "pairs": pairs, "steps": steps,
    }
