#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
from pathlib import Path

PACKAGE = "id.ac.ub.rupiahbenchmark"
ACTIVITY = f"{PACKAGE}/.BenchmarkActivity"
REMOTE = f"/sdcard/Android/data/{PACKAGE}/files/results"

def adb(*args, capture=True):
    cmd = ["adb", *map(str, args)]
    return subprocess.run(cmd, check=True, text=True, capture_output=capture).stdout.strip() if capture else subprocess.run(cmd, check=True).returncode

def wait_file(name, timeout=180):
    path, end = f"{REMOTE}/{name}", time.time() + timeout
    while time.time() < end:
        r = subprocess.run(["adb", "shell", "test", "-f", path], capture_output=True)
        if r.returncode == 0:
            return
        time.sleep(0.25)
    raise TimeoutError(f"Timeout menunggu {name}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path.cwd() / "stage6_android_verification.json")
    args = p.parse_args()
    adb("get-state")
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "rm", "-rf", REMOTE)
    adb("shell", "am", "start", "-n", ACTIVITY, "--es", "mode", "stage6_verify")
    wait_file("stage6_verify.done")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    adb("pull", f"{REMOTE}/stage6_android_verification.json", str(args.out), capture=False)
    report = json.loads(args.out.read_text())
    if not report.get("all_passed"):
        raise SystemExit("Stage 6 Android verification gagal. Lihat report.")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport: {args.out}")

if __name__ == "__main__":
    main()
