#!/usr/bin/env python3
"""Benchmark Android Tahap 7 dengan checkpoint atomik per sesi."""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

PACKAGE = "id.ac.ub.rupiahbenchmark"
ACTIVITY = f"{PACKAGE}/.BenchmarkActivity"
REMOTE = f"/sdcard/Android/data/{PACKAGE}/files/results"
CANDIDATES = ("fp32", "fp16", "dynamic_range", "full_int8")
TFLITE_VERSION, IDLE_SECONDS = "2.17.0", 300
LATENCY_FIELDS = ["candidate", "model_sha256", "session", "measurement_type", "index", "tensor_index", "time_ms"]
MEMORY_FIELDS = ["candidate", "model_sha256", "session", "phase", "snapshot", "total_pss_kb"]

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def adb(*args, check=True):
    r = subprocess.run(["adb", *map(str, args)], text=True, capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f"adb {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()

def require_adb():
    r = subprocess.run(["adb", "get-state"], text=True, capture_output=True)
    require(r.returncode == 0 and r.stdout.strip() == "device", "Koneksi ADB terputus.")

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def force_stop():
    adb("shell", "am", "force-stop", PACKAGE, check=False)

def kill_background():
    adb("shell", "am", "kill-all", check=False)
    for line in adb("shell", "pm", "list", "packages", "-3", check=False).splitlines():
        pkg = line.replace("package:", "").strip()
        if pkg and pkg != PACKAGE:
            adb("shell", "am", "force-stop", pkg, check=False)

def remove_remote(*names):
    for name in names:
        adb("shell", "rm", "-f", f"{REMOTE}/{name}", check=False)

def wait_remote(name, timeout=300):
    path, end = f"{REMOTE}/{name}", time.time() + timeout
    while time.time() < end:
        require_adb()
        if subprocess.run(["adb", "shell", "test", "-f", path], capture_output=True).returncode == 0:
            return
        time.sleep(0.25)
    raise TimeoutError(f"Timeout menunggu {name}")

def pull(name, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["adb", "pull", f"{REMOTE}/{name}", str(target)], text=True, capture_output=True)
    require(r.returncode == 0, f"Gagal adb pull {name}\n{r.stdout}\n{r.stderr}")

def launch(mode, candidate=None, session=None):
    cmd = ["shell", "am", "start", "-n", ACTIVITY, "--es", "mode", mode]
    if candidate is not None:
        cmd += ["--es", "candidate", candidate]
    if session is not None:
        cmd += ["--ei", "session", str(session)]
    adb(*cmd)

def battery_state():
    text = adb("shell", "dumpsys", "battery")
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip().lower()
    level = int(fields.get("level", "-1"))
    powered = any(fields.get(k, "false") == "true" for k in ("ac powered", "usb powered", "wireless powered", "dock powered"))
    return level, powered, text

def preflight(path):
    level, powered, battery = battery_state()
    settings = {
        "airplane_mode": adb("shell", "settings", "get", "global", "airplane_mode_on"),
        "brightness": adb("shell", "settings", "get", "system", "screen_brightness"),
        "brightness_mode": adb("shell", "settings", "get", "system", "screen_brightness_mode"),
        "low_power": adb("shell", "settings", "get", "global", "low_power"),
    }
    model = adb("shell", "getprop", "ro.product.model")
    android = adb("shell", "getprop", "ro.build.version.release")
    Path(path).write_text(
        f"device_model={model}\nandroid={android}\nlevel={level}\npowered={powered}\n"
        + "\n".join(f"{k}={v}" for k, v in settings.items()) + f"\n\n{battery}\n"
    )
    require(50 <= level <= 80, f"Baterai harus 50-80%, sekarang {level}%")
    require(not powered, "Perangkat masih charging.")
    require(settings["airplane_mode"] == "1", "Mode pesawat belum aktif.")
    require(settings["brightness_mode"] == "0", "Kecerahan harus manual.")
    require(settings["brightness"].isdigit() and 28 <= int(settings["brightness"]) <= 36,
            f"Brightness POCO X5 Pro 5G harus sekitar raw 32; sekarang {settings['brightness']}.")
    require(settings["low_power"] in ("0", "null", ""), "Mode hemat daya masih aktif.")
    return model, android

def pss_kb(raw):
    m = re.search(r"TOTAL PSS:\s*(\d+)", raw)
    if m:
        return int(m.group(1))
    for line in raw.splitlines():
        if re.match(r"^\s*TOTAL\s+\d+", line):
            return int(line.split()[1])
    raise RuntimeError("TOTAL PSS tidak ditemukan pada dumpsys meminfo")

def read_csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, fields, rows):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    tmp.replace(path)

def as_int(value):
    return int(float(value))

def valid_block(rows, candidate, session, digest, kind):
    try:
        rows = [r for r in rows if r["candidate"] == candidate and as_int(r["session"]) == session]
        if kind == "latency":
            if len(rows) != 502 or any(r["model_sha256"] != digest or float(r["time_ms"]) <= 0 for r in rows):
                return False
            counts = {k: [r for r in rows if r["measurement_type"] == k] for k in ("initialization", "first_inference", "stable")}
            stable = sorted(counts["stable"], key=lambda r: as_int(r["index"]))
            return (len(counts["initialization"]) == len(counts["first_inference"]) == 1 and len(stable) == 500
                    and [as_int(r["index"]) for r in stable] == list(range(1, 501))
                    and [as_int(r["tensor_index"]) for r in stable] == [i % 80 for i in range(500)])
        if len(rows) != 20 or any(r["model_sha256"] != digest or int(r["total_pss_kb"]) <= 0 for r in rows):
            return False
        return all(sorted(as_int(r["snapshot"]) for r in rows if r["phase"] == phase) == list(range(1, n + 1))
                   for phase, n in (("baseline", 5), ("active", 15)))
    except Exception:
        return False

def checkpoint(path, fields, hashes, kind, clean=True):
    rows = read_csv(path)
    complete = []
    for session in range(1, 6):
        if all(valid_block(rows, c, session, hashes[c], kind) for c in CANDIDATES):
            complete.append(session)
        else:
            break
    keep = [r for r in rows if as_int(r["session"]) in complete]
    if clean and len(keep) != len(rows):
        write_csv(path, fields, keep)
    return keep, complete

def append_rows(path, fields, base, new):
    base.extend(new)
    write_csv(path, fields, base)

def smoke_ok(path):
    try:
        return bool(json.loads(Path(path).read_text()).get("all_passed"))
    except Exception:
        return False

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage7-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, help="Gunakan folder yang sama untuk melanjutkan checkpoint.")
    p.add_argument("--status", action="store_true", help="Audit checkpoint tanpa ADB.")
    args = p.parse_args()

    stage7 = args.stage7_dir.resolve()
    bundle = stage7 / "android_bundle/stage7"
    spec_path = bundle / "benchmark_spec.json"
    protocol_template = stage7 / "android_protocol_template.json"
    require(spec_path.is_file() and protocol_template.is_file(),
            "Jalankan 07_compare_select.py tanpa CSV benchmark terlebih dahulu.")
    spec = json.loads(spec_path.read_text())
    hashes = {x["candidate"]: x["model_sha256"] for x in spec["candidates"]}
    require(set(hashes) == set(CANDIDATES), "benchmark_spec tidak memuat empat kandidat.")

    out = (args.out or stage7 / "android_results" / datetime.now().strftime("run_%Y%m%d_%H%M%S")).resolve()
    latency_path, memory_path = out / "stage7_latency.csv", out / "stage7_memory.csv"
    latency, lat_done = checkpoint(latency_path, LATENCY_FIELDS, hashes, "latency", clean=not args.status)
    memory, mem_done = checkpoint(memory_path, MEMORY_FIELDS, hashes, "memory", clean=not args.status)
    state = {"run_dir": str(out), "latency_sessions": lat_done, "memory_sessions": mem_done,
             "latency_rows": len(latency), "memory_rows": len(memory),
             "smoke_passed": smoke_ok(out / "stage7_smoke_report.json")}
    state["complete"] = lat_done == mem_done == [1, 2, 3, 4, 5] and len(latency) == 10040 and len(memory) == 400
    if args.status:
        print(json.dumps(state, indent=2, ensure_ascii=False)); return
    if state["complete"] and (out / "android_protocol.json").is_file():
        print(json.dumps({**state, "status": "complete"}, indent=2, ensure_ascii=False)); return

    out.mkdir(parents=True, exist_ok=True)
    evidence = out / "evidence"; evidence.mkdir(exist_ok=True)
    require_adb()
    if not any((out / name).exists() for name in ("stage7_latency.csv", "stage7_memory.csv", "stage7_smoke_report.json")):
        force_stop(); adb("shell", "rm", "-rf", REMOTE, check=False)
    model, android = preflight(evidence / ("preflight_initial.txt" if not lat_done and not mem_done else "preflight_resume.txt"))

    smoke_path = out / "stage7_smoke_report.json"
    if not smoke_ok(smoke_path):
        remove_remote("stage7_smoke.done", "stage7_smoke_report.json", "last_error.txt")
        launch("stage7_smoke"); wait_remote("stage7_smoke.done")
        pull("stage7_smoke_report.json", smoke_path)
        require(smoke_ok(smoke_path), "Android smoke Stage 7 gagal.")
        force_stop()

    for session in range(len(lat_done) + 1, 6):
        print(f"\nLATENCY SESSION {session}")
        remove_remote("stage7_latency.csv", *[f"latency_{c}_{session}.done" for c in CANDIDATES])
        try:
            for candidate in CANDIDATES:
                print(f"Latency {candidate} sesi {session}")
                force_stop(); kill_background()
                preflight(evidence / f"preflight_latency_s{session}_{candidate}.txt")
                time.sleep(IDLE_SECONDS)
                preflight(evidence / f"preflight_latency_after_idle_s{session}_{candidate}.txt")
                launch("latency", candidate, session)
                wait_remote(f"latency_{candidate}_{session}.done", timeout=900)
                force_stop()
            temp = out / ".latency_session.csv"
            pull("stage7_latency.csv", temp)
            rows = read_csv(temp); temp.unlink(missing_ok=True)
            require(all(valid_block(rows, c, session, hashes[c], "latency") for c in CANDIDATES),
                    f"Latency sesi {session} tidak lengkap.")
            append_rows(latency_path, LATENCY_FIELDS, latency, rows)
            lat_done.append(session)
            print(f"Checkpoint latency sesi {session}: OK")
        except Exception:
            force_stop(); print("Latency terputus; sesi ini akan diulang pada run berikutnya."); raise

    for session in range(len(mem_done) + 1, 6):
        print(f"\nMEMORY SESSION {session}")
        session_rows = []
        try:
            for candidate in CANDIDATES:
                print(f"Memory {candidate} sesi {session}")
                force_stop(); kill_background()
                remove_remote(f"baseline_{candidate}_{session}.ready", f"active_{candidate}_{session}.ready", f"active_{candidate}_{session}.done")
                preflight(evidence / f"preflight_memory_s{session}_{candidate}.txt")
                launch("memory_baseline", candidate, session)
                wait_remote(f"baseline_{candidate}_{session}.ready"); time.sleep(10)
                rows = []
                for snapshot in range(1, 6):
                    require_adb(); rows.append({"candidate": candidate, "model_sha256": hashes[candidate], "session": session,
                                                "phase": "baseline", "snapshot": snapshot,
                                                "total_pss_kb": pss_kb(adb("shell", "dumpsys", "meminfo", PACKAGE))})
                    if snapshot < 5: time.sleep(2)
                launch("memory_active", candidate, session); wait_remote(f"active_{candidate}_{session}.ready")
                for snapshot in range(1, 16):
                    require_adb(); rows.append({"candidate": candidate, "model_sha256": hashes[candidate], "session": session,
                                                "phase": "active", "snapshot": snapshot,
                                                "total_pss_kb": pss_kb(adb("shell", "dumpsys", "meminfo", PACKAGE))})
                    if snapshot < 15: time.sleep(2)
                wait_remote(f"active_{candidate}_{session}.done", timeout=60); force_stop()
                require(valid_block(rows, candidate, session, hashes[candidate], "memory"),
                        f"Memory {candidate} sesi {session} tidak lengkap.")
                session_rows.extend(rows)
            append_rows(memory_path, MEMORY_FIELDS, memory, session_rows)
            mem_done.append(session)
            print(f"Checkpoint memory sesi {session}: OK")
        except Exception:
            force_stop(); print("Memory terputus; seluruh sesi ini akan diulang pada run berikutnya."); raise

    require(lat_done == mem_done == [1, 2, 3, 4, 5] and len(latency) == 10040 and len(memory) == 400,
            "Benchmark final belum lengkap.")
    protocol = json.loads(protocol_template.read_text())
    protocol["runtime"]["android_version"] = android
    protocol["runtime"]["tflite_version"] = TFLITE_VERSION
    protocol["latency_csv_sha256"], protocol["memory_csv_sha256"] = sha256(latency_path), sha256(memory_path)
    protocol["evidence_directory"] = str(evidence)
    for key in protocol["checks"]:
        protocol["checks"][key] = True
    protocol_path = out / "android_protocol.json"
    protocol_path.write_text(json.dumps(protocol, indent=2, ensure_ascii=False))
    summary = {"device_reported": model, "android_version": android, "latency_csv": str(latency_path),
               "memory_csv": str(memory_path), "protocol_json": str(protocol_path), "tflite_version": TFLITE_VERSION,
               "checkpoint_mode": "atomic_session"}
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\nBenchmark Stage 7 selesai.\n" + json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
