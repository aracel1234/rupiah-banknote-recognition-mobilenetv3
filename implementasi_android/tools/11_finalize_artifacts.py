#!/usr/bin/env python3
"""Finalize and lock the Android implementation artifacts for thesis Subchapter 5.11.

This script does not change recognition logic or calibration parameters. It verifies
that the final operational configuration has been integrated, verifies locked model
artifacts, checks that the debug APK embeds the same critical assets, and writes
final traceability manifests for the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_APP_STATUS = "operational_config_locked"
EXPECTED_APP_SCHEMA = 2
EXPECTED_REVISION = "calib-operational-001"
EXPECTED_POST_STATUS = "calibrated_sequence_locked"
EXPECTED_OPERATIONAL_LOCK_SHA256 = "f45b1bb88fab2a520b3e46a0f769881056938a212f452324cea4d8eb9939420a"

CRITICAL_SOURCE_FILES = [
    "app/build.gradle.kts",
    "app/src/main/AndroidManifest.xml",
    "app/src/main/java/id/ac/ub/rupiah/config/AppConfig.kt",
    "app/src/main/java/id/ac/ub/rupiah/camera/CameraController.kt",
    "app/src/main/java/id/ac/ub/rupiah/image/RoiGeometry.kt",
    "app/src/main/java/id/ac/ub/rupiah/image/QualityGate.kt",
    "app/src/main/java/id/ac/ub/rupiah/image/FramePreprocessor.kt",
    "app/src/main/java/id/ac/ub/rupiah/inference/ModelRunner.kt",
    "app/src/main/java/id/ac/ub/rupiah/prediction/TemporalDecision.kt",
    "app/src/main/java/id/ac/ub/rupiah/session/RecognitionSession.kt",
    "app/src/main/java/id/ac/ub/rupiah/speech/SpeechOutput.kt",
    "app/src/main/java/id/ac/ub/rupiah/logging/EventLog.kt",
    "app/src/main/java/id/ac/ub/rupiah/testing/TestTelemetry.kt",
    "app/src/main/java/id/ac/ub/rupiah/ui/MainActivity.kt",
    "app/src/main/java/id/ac/ub/rupiah/ui/RoiOverlay.kt",
    "app/src/main/res/layout/activity_main.xml",
]

CRITICAL_ASSET_FILES = [
    "app/src/main/assets/app_config.json",
    "app/src/main/assets/calibration/static_quality_config.json",
    "app/src/main/assets/calibration/static_quality_config_lock.json",
    "app/src/main/assets/calibration/operational_config.json",
    "app/src/main/assets/calibration/operational_config_lock.json",
    "app/src/main/assets/model/model.tflite",
    "app/src/main/assets/model/class_names.json",
    "app/src/main/assets/model/tensor_contract.json",
    "app/src/main/assets/model/model_identity.json",
    "app/src/main/assets/model/selection_lock.json",
    "app/src/main/assets/model/asset_integrity.json",
]

APK_ASSET_MAP = {
    "assets/app_config.json": "app/src/main/assets/app_config.json",
    "assets/calibration/static_quality_config.json": "app/src/main/assets/calibration/static_quality_config.json",
    "assets/calibration/static_quality_config_lock.json": "app/src/main/assets/calibration/static_quality_config_lock.json",
    "assets/calibration/operational_config.json": "app/src/main/assets/calibration/operational_config.json",
    "assets/calibration/operational_config_lock.json": "app/src/main/assets/calibration/operational_config_lock.json",
    "assets/model/model.tflite": "app/src/main/assets/model/model.tflite",
    "assets/model/class_names.json": "app/src/main/assets/model/class_names.json",
    "assets/model/tensor_contract.json": "app/src/main/assets/model/tensor_contract.json",
    "assets/model/model_identity.json": "app/src/main/assets/model/model_identity.json",
    "assets/model/selection_lock.json": "app/src/main/assets/model/selection_lock.json",
    "assets/model/asset_integrity.json": "app/src/main/assets/model/asset_integrity.json",
}

GENERATED_PATHS = {
    "docs/implementation_snapshot.json",
    "docs/final_artifact_lock.json",
    "FINAL_SHA256SUMS.txt",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def compare_value(name: str, actual, expected, tol: float = 1e-9):
    if isinstance(expected, float):
        require(abs(float(actual) - expected) <= tol, f"{name} tidak sesuai: {actual!r} != {expected!r}")
    else:
        require(actual == expected, f"{name} tidak sesuai: {actual!r} != {expected!r}")


def parse_gradle(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    def grab(pattern: str, cast=str):
        m = re.search(pattern, text)
        return cast(m.group(1)) if m else None
    return {
        "application_id": grab(r'applicationId\s*=\s*"([^"]+)"'),
        "compile_sdk": grab(r'compileSdk\s*=\s*(\d+)', int),
        "min_sdk": grab(r'minSdk\s*=\s*(\d+)', int),
        "target_sdk": grab(r'targetSdk\s*=\s*(\d+)', int),
        "version_code": grab(r'versionCode\s*=\s*(\d+)', int),
        "version_name": grab(r'versionName\s*=\s*"([^"]+)"'),
        "jvm_target": grab(r'jvmTarget\s*=\s*"([^"]+)"'),
    }


def git_info(project: Path) -> dict:
    def run(*args):
        try:
            p = subprocess.run(
                ["git", *args], cwd=project, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
            )
            return p.stdout.strip()
        except Exception:
            return None
    head = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {
        "commit": head,
        "working_tree_clean": None if status is None else status == "",
    }


def validate_final_config(project: Path) -> tuple[dict, dict, dict]:
    app_path = project / "app/src/main/assets/app_config.json"
    op_path = project / "app/src/main/assets/calibration/operational_config.json"
    lock_path = project / "app/src/main/assets/calibration/operational_config_lock.json"

    app = read_json(app_path)
    op = read_json(op_path)
    lock = read_json(lock_path)

    require(app["schema_version"] == EXPECTED_APP_SCHEMA, "app_config.json belum schema_version 2")
    require(app["status"] == EXPECTED_APP_STATUS, "app_config.json belum operational_config_locked")
    require(app["revision"] == EXPECTED_REVISION, "revision app_config.json tidak sesuai")
    require(app["postinference_status"] == EXPECTED_POST_STATUS, "postinference_status belum final")

    require(lock["status"] == "operational_configuration_locked", "Status operational_config_lock.json tidak valid")
    require(sha256_file(lock_path) == EXPECTED_OPERATIONAL_LOCK_SHA256, "SHA-256 operational_config_lock.json berubah")

    out_hashes = lock["output_sha256"]
    require(sha256_file(op_path) == out_hashes["operational_config.json"], "operational_config.json tidak sesuai lock")
    require(sha256_file(app_path) == out_hashes["android_app_config_final.json"], "app_config.json bukan android_app_config_final.json hasil 5.7")

    selected = lock["selected_values"]
    keys = [
        "revision", "analysis_fps", "threads", "roi_width_fraction", "roi_aspect_ratio",
        "roi_height_cap_fraction", "blur_variance_min", "luma_min", "luma_max",
        "confidence_threshold", "temporal_window_ms", "minimum_results", "clahe_enabled",
        "clahe_clip_limit", "clahe_grid", "yuv_range", "log_enabled",
    ]
    for key in keys:
        compare_value(f"app_config.{key}", app[key], selected[key])
        compare_value(f"operational_config.{key}", op[key], selected[key])

    require(
        app["static_quality_lock_sha256"] == lock["dependencies"]["static_quality_lock_sha256"],
        "static_quality_lock_sha256 pada app_config tidak sesuai operational lock",
    )

    # The post-inference logic used for calibration must remain unchanged after the final parameter patch.
    baseline = lock["dependencies"].get("android_source_hashes_before_final_patch", {})
    for rel, key in [
        ("app/src/main/java/id/ac/ub/rupiah/prediction/TemporalDecision.kt", "TemporalDecision.kt"),
        ("app/src/main/java/id/ac/ub/rupiah/session/RecognitionSession.kt", "RecognitionSession.kt"),
    ]:
        if key in baseline:
            require(sha256_file(project / rel) == baseline[key], f"{key} berubah setelah kalibrasi 5.7.3")

    return app, op, lock


def validate_model_assets(project: Path) -> dict:
    model_dir = project / "app/src/main/assets/model"
    integrity = read_json(model_dir / "asset_integrity.json")
    verified = {}
    for name, expected in integrity.items():
        path = model_dir / name
        require(path.is_file(), f"Aset model hilang: {path}")
        actual = sha256_file(path)
        require(actual == expected, f"SHA-256 aset model tidak sesuai: {name}")
        verified[name] = actual

    identity = read_json(model_dir / "model_identity.json")
    selection = read_json(model_dir / "selection_lock.json")
    require(identity["candidate"] == "dynamic_range", "Kandidat model bukan dynamic_range")
    require(selection["selected_candidate"] == "dynamic_range", "selection_lock bukan dynamic_range")
    require(identity["sha256"] == verified["model.tflite"], "model_identity tidak sesuai model.tflite")
    require(selection["model_sha256"] == verified["model.tflite"], "selection_lock tidak sesuai model.tflite")
    return {
        "candidate": "dynamic_range",
        "model_sha256": verified["model.tflite"],
        "size_bytes": (model_dir / "model.tflite").stat().st_size,
        "asset_sha256": verified,
    }


def find_apks(project: Path, explicit: list[str]) -> list[Path]:
    if explicit:
        apks = [Path(x).expanduser().resolve() for x in explicit]
    else:
        apks = sorted((project / "app/build/outputs/apk/debug").glob("*.apk"))
    require(bool(apks), "APK debug belum ditemukan. Jalankan ./gradlew :app:clean :app:assembleDebug terlebih dahulu.")
    for apk in apks:
        require(apk.is_file(), f"APK tidak ditemukan: {apk}")
    return apks


def verify_apk_assets(project: Path, apk: Path) -> dict:
    checks = {}
    with zipfile.ZipFile(apk, "r") as z:
        names = set(z.namelist())
        for apk_name, src_rel in APK_ASSET_MAP.items():
            require(apk_name in names, f"{apk.name} tidak memuat {apk_name}")
            embedded_hash = sha256_bytes(z.read(apk_name))
            source_hash = sha256_file(project / src_rel)
            require(embedded_hash == source_hash, f"{apk.name}: {apk_name} berbeda dari source")
            checks[apk_name] = embedded_hash
    return {
        "name": apk.name,
        "path": str(apk),
        "size_bytes": apk.stat().st_size,
        "sha256": sha256_file(apk),
        "embedded_assets_match_source": True,
        "embedded_asset_sha256": checks,
    }


def build_snapshot(project: Path, app_status: str) -> dict:
    snapshot_files = [
        "settings.gradle.kts",
        "build.gradle.kts",
        "gradle.properties",
        *CRITICAL_SOURCE_FILES,
        *CRITICAL_ASSET_FILES,
    ]
    files = {}
    for rel in snapshot_files:
        path = project / rel
        require(path.is_file(), f"Berkas snapshot tidak ditemukan: {rel}")
        files[rel] = sha256_file(path)
    return {
        "snapshot_utc": datetime.now(timezone.utc).isoformat(),
        "app_parameter_status": app_status,
        "system_testing_performed_by_this_script": False,
        "finalization_stage": "5.11",
        "scope": "critical Android source, configuration, model assets, and build metadata",
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apk", action="append", default=[], help="Path APK; may be repeated. If omitted, discovers app/build/outputs/apk/debug/*.apk")
    args = parser.parse_args()
    project = args.project.expanduser().resolve()

    try:
        for rel in CRITICAL_SOURCE_FILES + CRITICAL_ASSET_FILES:
            require((project / rel).is_file(), f"Berkas wajib tidak ditemukan: {rel}")

        app, op, op_lock = validate_final_config(project)
        model = validate_model_assets(project)
        apks = find_apks(project, args.apk)
        apk_reports = [verify_apk_assets(project, p) for p in apks]

        docs = project / "docs"
        docs.mkdir(parents=True, exist_ok=True)

        snapshot = build_snapshot(project, app["status"])
        snapshot_path = docs / "implementation_snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        source_hashes = {rel: sha256_file(project / rel) for rel in CRITICAL_SOURCE_FILES}
        config_hashes = {rel: sha256_file(project / rel) for rel in CRITICAL_ASSET_FILES[:5]}

        report = {
            "status": "final_android_artifacts_locked",
            "locked_at_utc": datetime.now(timezone.utc).isoformat(),
            "thesis_stage": "5.11",
            "operational_revision": app["revision"],
            "application": parse_gradle(project / "app/build.gradle.kts"),
            "git": git_info(project),
            "configuration": {
                "app_config_status": app["status"],
                "postinference_status": app["postinference_status"],
                "selected_values": op_lock["selected_values"],
                "sha256": config_hashes,
                "operational_lock_sha256": sha256_file(project / "app/src/main/assets/calibration/operational_config_lock.json"),
            },
            "model": model,
            "critical_source_sha256": source_hashes,
            "implementation_snapshot": {
                "path": "docs/implementation_snapshot.json",
                "sha256": sha256_file(snapshot_path),
            },
            "apk_artifacts": apk_reports,
            "verification": {
                "operational_configuration_matches_5_7_lock": True,
                "postinference_logic_unchanged_since_calibration": True,
                "model_assets_match_integrity_manifest": True,
                "apk_critical_assets_match_project_source": True,
                "system_testing_performed_by_this_script": False,
            },
        }

        lock_path = docs / "final_artifact_lock.json"
        lock_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        checksum_items = {}
        for rel in CRITICAL_SOURCE_FILES + CRITICAL_ASSET_FILES:
            checksum_items[rel] = sha256_file(project / rel)
        checksum_items["docs/implementation_snapshot.json"] = sha256_file(snapshot_path)
        checksum_items["docs/final_artifact_lock.json"] = sha256_file(lock_path)
        for apk in apks:
            try:
                rel = str(apk.relative_to(project)).replace("\\", "/")
            except ValueError:
                rel = str(apk)
            checksum_items[rel] = sha256_file(apk)

        sums_path = project / "FINAL_SHA256SUMS.txt"
        sums_path.write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(checksum_items.items())),
            encoding="utf-8",
        )

        print("FINALISASI 5.11: PASS")
        print(f"Status konfigurasi : {app['status']}")
        print(f"Revisi              : {app['revision']}")
        print(f"Model               : {model['candidate']}")
        print(f"Model SHA-256       : {model['model_sha256']}")
        print(f"Snapshot            : {snapshot_path}")
        print(f"Final artifact lock : {lock_path}")
        print(f"Checksum final      : {sums_path}")
        print("APK:")
        for item in apk_reports:
            print(f"  - {item['name']} | {item['size_bytes']} bytes | {item['sha256']}")
        print("\nSimpan tiga berkas keluaran di atas. Nilai hash aktualnya dipakai pada Subbab 5.11.")
        return 0
    except Exception as exc:
        print(f"FINALISASI 5.11: FAIL\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
