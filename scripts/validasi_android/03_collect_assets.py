#!/usr/bin/env python3
"""Pengumpulan bukti POCO lewat ADB; Python 3 standar, tanpa mengubah aplikasi."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = "id.ac.ub.rupiah"


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


class Collector:
    def __init__(self, adb, serial, output):
        self.command = [adb, "-s", serial]
        self.root = output
        self.index = 0
        self.first_ms = self.uptime()
        self.boot = self.text("shell", "cat", "/proc/sys/kernel/random/boot_id")

    def run(self, *args, timeout=25):
        try:
            p = subprocess.run(self.command + list(args), capture_output=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr.decode(errors="replace")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return -1, b"", str(exc)

    def text(self, *args):
        code, data, _ = self.run(*args)
        return data.decode(errors="replace").strip() if code == 0 else ""

    def uptime(self):
        text = self.text("shell", "cat", "/proc/uptime")
        try:
            return int(float(text.split()[0]) * 1000)
        except (ValueError, IndexError):
            return None

    def mark(self, label, observation=""):
        row = dict(host_utc=utc(), device_elapsed_ms=self.uptime(),
                   label=label, observation=observation)
        with (self.root / "tindakan.jsonl").open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def save_command(self, path, *args, timeout=25):
        code, data, error = self.run(*args, timeout=timeout)
        if code == 0:
            path.write_bytes(data)
            return True
        path.with_suffix(path.suffix + ".error.txt").write_text(error or data.decode(errors="replace"))
        print("Tidak tersedia:", path.name, "(lihat .error.txt)")
        return False

    def checkpoint(self, label, screenshot=True, hierarchy=False):
        self.index += 1
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")[:70] or "checkpoint"
        folder = self.root / "checkpoint" / f"{self.index:03d}_{safe}"
        folder.mkdir(parents=True)
        self.mark(label)
        for name in ("events.previous.jsonl", "events.jsonl"):
            self.save_command(folder / name, "exec-out", "run-as", PACKAGE, "cat", "files/" + name)
        if screenshot:
            path = folder / "layar.png"
            if self.save_command(path, "exec-out", "screencap", "-p"):
                if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    path.rename(folder / "layar_invalid.bin")
                    print("Screenshot bukan PNG valid; ulangi pengambilan.")
        self.save_command(folder / "meminfo.txt", "shell", "dumpsys", "meminfo", PACKAGE)
        self.save_command(folder / "accessibility_services.txt", "shell", "settings", "get",
                          "secure", "enabled_accessibility_services")
        if hierarchy:
            remote = f"/sdcard/rupiah_ui_{time.time_ns()}.xml"
            code, _, _ = self.run("shell", "uiautomator", "dump", remote, timeout=20)
            if code == 0 and self.save_command(folder / "ui.xml", "exec-out", "cat", remote):
                self.run("shell", "rm", remote)
            else:
                (folder / "ui_unavailable.txt").write_text("Dump UI gagal/timeout. Gunakan screenshot dan observasi TalkBack.")
        print("Checkpoint:", folder)

    def snapshot(self, project):
        dest = self.root / "snapshot"
        dest.mkdir()
        self.save_command(dest / "package.txt", "shell", "dumpsys", "package", PACKAGE)
        info = {key: self.text("shell", "getprop", prop) for key, prop in {
            "manufacturer": "ro.product.manufacturer", "model": "ro.product.model",
            "device": "ro.product.device", "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk"}.items()}
        info.update(serial=self.command[2], host_utc=utc(), start_elapsed_ms=self.first_ms)
        write_json(dest / "device.json", info)
        roots = [project / "app/src/main", project / "docs"]
        files = [p for root in roots for p in root.rglob("*") if p.is_file()
                 and p.suffix in {".kt", ".xml", ".json"}]
        files += [project / p for p in ("build.gradle.kts", "settings.gradle.kts",
                  "app/build.gradle.kts", "gradle/wrapper/gradle-wrapper.properties")]
        with zipfile.ZipFile(dest / "sumber_proyek.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for path in files:
                if path.is_file():
                    z.write(path, str(path.relative_to(project)))
        # Read the installed APK, extract only its assets and identity, discard the local temporary copy.
        paths = self.text("shell", "pm", "path", PACKAGE).splitlines()
        apk = next((x.removeprefix("package:") for x in paths if x.endswith("/base.apk")), "")
        comparison = {}
        if apk:
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "base.apk"
                code, _, _ = self.run("pull", apk, str(local), timeout=120)
                if code == 0 and zipfile.is_zipfile(local):
                    comparison["installed_base_apk_sha256"] = digest(local.read_bytes())
                    with zipfile.ZipFile(local) as z:
                        for name in ("app_config.json", "model/model.tflite", "model/class_names.json",
                                     "model/tensor_contract.json", "model/model_identity.json",
                                     "model/asset_integrity.json", "model/selection_lock.json"):
                            member = "assets/" + name
                            if member not in z.namelist():
                                comparison[name] = {"error": "Aset tidak ditemukan dalam base.apk"}
                                continue
                            data = z.read(member)
                            source = project / "app/src/main/assets" / name
                            comparison[name] = {"apk_sha256": digest(data),
                                "project_sha256": digest(source.read_bytes()) if source.is_file() else None,
                                "same": source.is_file() and source.read_bytes() == data}
                            if name.endswith(".json"):
                                target = dest / "installed_assets" / name
                                target.parent.mkdir(parents=True, exist_ok=True)
                                target.write_bytes(data)
        write_json(dest / "asset_comparison.json", comparison or {"error": "APK tidak berhasil dibaca"})
        if not comparison or any(isinstance(v, dict) and v.get("same") is not True for v in comparison.values()):
            print("PERHATIAN: periksa snapshot/asset_comparison.json sebelum menyamakan proyek dengan APK.")

    def record(self, label):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:60] or "video"
        stem = f"{time.time_ns()}_{safe}"
        remote = f"/sdcard/rupiah_{stem}.mp4"
        local = self.root / "video" / f"{stem}.mp4"
        local.parent.mkdir(exist_ok=True)
        self.mark("video_start_" + label)
        print("Merekam 60 detik TANPA AUDIO. Sekarang lakukan tindakan di HP; tunggu sampai selesai.")
        code, _, error = self.run("shell", "screenrecord", "--bit-rate", "3000000",
                                  "--time-limit", "60", remote, timeout=75)
        if code == 0:
            code, _, error = self.run("pull", remote, str(local), timeout=60)
            if code == 0:
                self.run("shell", "rm", remote)  # Only this script's successfully copied temporary video.
                print("Video:", local)
        if code != 0:
            (local.parent / f"{stem}.error.txt").write_text(error + "\nRemote: " + remote)
            print("Rekaman gagal. Gunakan perekam bawaan POCO atau kamera lain.")
        self.mark("video_end_" + label)
        self.checkpoint("sesudah_video_" + label, screenshot=False)

    def finish(self):
        self.checkpoint("akhir", screenshot=False)
        end = self.uptime()
        boot = self.text("shell", "cat", "/proc/sys/kernel/random/boot_id")
        can_filter = self.first_ms is not None and end is not None and end >= self.first_ms
        can_filter = can_filter and bool(self.boot) and boot == self.boot
        seen, selected, invalid = set(), [], 0
        for path in sorted((self.root / "checkpoint").rglob("*.jsonl")):
            for line in path.read_text(errors="replace").splitlines():
                try:
                    row = json.loads(line)
                    key = json.dumps(row, sort_keys=True)
                    elapsed = row.get("elapsed_ms")
                    if can_filter and isinstance(elapsed, (int, float)) and self.first_ms <= elapsed <= end and key not in seen:
                        seen.add(key)
                        selected.append(row)
                except (ValueError, TypeError):
                    invalid += 1
        selected.sort(key=lambda x: x["elapsed_ms"])
        (self.root / "events_periode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in selected))
        write_json(self.root / "ringkasan.json", dict(filter_valid=can_filter, malformed_lines=invalid,
            event_counts=dict(Counter(r.get("event") for r in selected)),
            note="Bukan keputusan lulus/gagal. Log dapat terpotong oleh rotasi; cocokkan dengan tindakan dan video."))
        files = {str(p.relative_to(self.root)): digest(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        write_json(self.root / "sha256.json", files)
        archive = shutil.make_archive(str(self.root), "zip", self.root.parent, self.root.name)
        print("\nSELESAI. Kirim ZIP ini:", archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.home() / "Downloads/Skripsi/implementasi_android")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "hasil")
    parser.add_argument("--serial", help="Wajib jika ada lebih dari satu perangkat")
    parser.add_argument("--adb", default=shutil.which("adb") or str(Path.home() / "Android/Sdk/platform-tools/adb"))
    args = parser.parse_args()
    if not (args.project / "app/src/main/AndroidManifest.xml").is_file():
        parser.error("Folder proyek tidak ditemukan. Isi --project dengan folder implementasi_android.")
    try:
        p = subprocess.run([args.adb, "devices"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        parser.error("ADB tidak tersedia. Isi --adb dengan lokasi platform-tools/adb dari Android SDK.")
    devices = [line.split()[0] for line in p.stdout.splitlines() if len(line.split()) == 2 and line.split()[1] == "device"]
    if args.serial and args.serial not in devices:
        parser.error("Serial tidak terhubung/diizinkan. Periksa kabel dan dialog USB debugging.")
    if not args.serial and len(devices) != 1:
        parser.error("Hubungkan tepat satu POCO yang diizinkan, atau gunakan --serial.\n" + p.stdout)
    args.out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="poco_" + datetime.now().strftime("%Y%m%d_%H%M%S_"), dir=args.out.resolve()))
    c = Collector(args.adb, args.serial or devices[0], root)
    print("Perangkat:", c.text("shell", "getprop", "ro.product.model"), "\nHasil:", root)
    if not c.text("shell", "pm", "path", PACKAGE):
        parser.error("Aplikasi id.ac.ub.rupiah belum terpasang pada perangkat terpilih.")
    if c.run("shell", "run-as", PACKAGE, "id")[0] != 0:
        parser.error("Log internal tidak dapat dibaca. Pasang build DEBUG proyek melalui Android Studio lalu ulangi.")
    c.snapshot(args.project.resolve())
    c.checkpoint("awal", screenshot=False)
    try:
        while True:
            print("\n1 Screenshot + log | 2 Penanda/catatan | 3 Video 60 dtk | 4 Screenshot + UI XML | 0 Selesai + ZIP")
            choice = input("Pilihan: ").strip()
            if choice == "0":
                break
            if choice not in {"1", "2", "3", "4"}:
                continue
            label = input("Nama (contoh 5_8_stop): ").strip()
            if choice == "2":
                c.mark(label, input("Catatan tindakan/hasil aktual: "))
            elif choice == "3":
                c.record(label)
            else:
                c.checkpoint(label, hierarchy=choice == "4")
    except (EOFError, KeyboardInterrupt):
        print("\nMengemas data yang sudah terkumpul.")
    c.finish()


if __name__ == "__main__":
    main()
