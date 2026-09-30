#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

EXPECTED_FRAME_COLUMNS = [
    'frame_index','elapsed_ms','stage_id','stage_title','expected_label','analysis_role',
    'image_timestamp_ns','rotation_degrees','roi_width','roi_height','luma_mean_original',
    'luma_mean_processed','laplacian_variance','clahe_applied','quality_pass','quality_code',
    'score_1000','score_2000','score_5000','score_10000','score_20000','score_50000',
    'score_100000','score_nonuang','top_label','top_score','preprocess_ms','inference_ms',
    'pipeline_ms'
]
EXPECTED_CLASSES = ['1000','2000','5000','10000','20000','50000','100000','nonuang']
EXPECTED_COUNTS = {'nominal': 28, 'nonuang': 6, 'transition': 6}
REQUIRED_SEQUENCE_FILES = ['metadata.json','frames.csv','config_snapshot.json','stages.json']


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def canonical_rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def directory_fingerprint(root: Path, relative_files: List[str]) -> Tuple[str, List[Dict[str, str]]]:
    items = []
    for rel in sorted(set(relative_files)):
        p = root / rel
        digest = sha256_file(p)
        items.append({'path': rel, 'sha256': digest})
    payload = ''.join(f"{x['sha256']}  {x['path']}\n" for x in items).encode('utf-8')
    return sha256_bytes(payload), items


def discover_sequence_dirs(root: Path) -> List[Path]:
    return sorted({p.parent for p in root.rglob('metadata.json') if '/sequences/' in p.as_posix()})


def bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().eq('true')


def validate_source(root: Path, expected_alias: str) -> Dict[str, Any]:
    if not root.is_dir():
        raise FileNotFoundError(f'Direktori dataset tidak ditemukan: {root}')

    top_required = [
        'checklist.csv','manifest.csv','collector_config.json','experiment_plan.json',
        'checklist.json','manifest.jsonl'
    ]
    missing_top = [x for x in top_required if not (root / x).is_file()]
    if missing_top:
        raise RuntimeError(f'{root}: berkas root hilang: {missing_top}')

    cfg = read_json(root / 'collector_config.json')
    plan = read_json(root / 'experiment_plan.json')

    if int(plan.get('per_device_total', -1)) != 40:
        raise RuntimeError(f'{root}: per_device_total bukan 40')
    if plan.get('candidate_replay_fps') != [3, 5]:
        raise RuntimeError(f'{root}: kandidat FPS tidak sesuai [3,5]')
    if plan.get('candidate_confidence_thresholds') != [0.5,0.55,0.6,0.65,0.7,0.75,0.8,0.85,0.9,0.95]:
        raise RuntimeError(f'{root}: kandidat confidence tidak sesuai')
    if plan.get('candidate_temporal_windows_ms') != [1000,1500,2000]:
        raise RuntimeError(f'{root}: kandidat window tidak sesuai')
    if int(plan.get('minimum_results', -1)) != 3:
        raise RuntimeError(f'{root}: minimum_results bukan 3')

    seq_dirs = discover_sequence_dirs(root)
    if len(seq_dirs) != 40:
        raise RuntimeError(f'{root}: sequence ditemukan {len(seq_dirs)}, harus 40')

    inventory_rows = []
    relevant_files = list(top_required)
    kinds = {}
    model_hashes, config_hashes = set(), set()
    class_orders = set()
    pipeline_quality_pass = []
    total_frames = total_qp = total_qr = 0
    hash_mismatches = []
    schema_mismatches = []
    duplicated_ids = []
    seen_ids = set()

    for seq_dir in seq_dirs:
        rel_dir = canonical_rel(root, seq_dir)
        for fn in REQUIRED_SEQUENCE_FILES:
            p = seq_dir / fn
            if not p.is_file():
                raise RuntimeError(f'{seq_dir}: {fn} hilang')
            relevant_files.append(f'{rel_dir}/{fn}')

        meta = read_json(seq_dir / 'metadata.json')
        stages = read_json(seq_dir / 'stages.json')
        snap = read_json(seq_dir / 'config_snapshot.json')
        sid = str(meta['sequence_id'])
        if sid in seen_ids:
            duplicated_ids.append(sid)
        seen_ids.add(sid)

        kind = str(meta['kind'])
        kinds[kind] = kinds.get(kind, 0) + 1
        model_hashes.add(str(meta['model_sha256']))
        config_hashes.add(str(meta['config_sha256']))
        class_orders.add(tuple(meta['class_names']))

        hash_checks = {
            'frames.csv': meta.get('frames_csv_sha256'),
            'stages.json': meta.get('stages_json_sha256'),
            'config_snapshot.json': meta.get('config_snapshot_sha256'),
        }
        for fn, expected in hash_checks.items():
            actual = sha256_file(seq_dir / fn)
            if actual != expected:
                hash_mismatches.append({'sequence_id': sid, 'file': fn, 'expected': expected, 'actual': actual})

        df = pd.read_csv(seq_dir / 'frames.csv', dtype={'expected_label': 'string'})
        if list(df.columns) != EXPECTED_FRAME_COLUMNS:
            schema_mismatches.append(sid)

        if df.empty:
            raise RuntimeError(f'{sid}: frames.csv kosong')
        if not df['frame_index'].astype(int).is_monotonic_increasing:
            raise RuntimeError(f'{sid}: frame_index tidak meningkat')
        if not df['elapsed_ms'].astype(int).is_monotonic_increasing:
            raise RuntimeError(f'{sid}: elapsed_ms tidak meningkat')
        if int(df['elapsed_ms'].max()) >= int(meta['duration_ms']) + 1000:
            raise RuntimeError(f'{sid}: timestamp jauh melewati durasi')

        qp = bool_series(df['quality_pass'])
        total_frames += len(df)
        total_qp += int(qp.sum())
        total_qr += int((~qp).sum())
        qpv = pd.to_numeric(df.loc[qp, 'pipeline_ms'], errors='coerce').dropna().astype(float).tolist()
        pipeline_quality_pass.extend(qpv)

        score_cols = [f'score_{x}' for x in EXPECTED_CLASSES]
        if df.loc[qp, score_cols].isna().any().any():
            raise RuntimeError(f'{sid}: ada skor kosong pada quality-pass')
        if df.loc[~qp, score_cols].notna().any().any():
            raise RuntimeError(f'{sid}: skor muncul pada quality-rejected')

        stage_ids = {str(x['stage_id']) for x in stages['stages']}
        bad_stage = sorted(set(df['stage_id'].astype(str)) - stage_ids)
        if bad_stage:
            raise RuntimeError(f'{sid}: stage_id tidak dikenal: {bad_stage}')

        inventory_rows.append({
            'device': expected_alias,
            'sequence_id': sid,
            'kind': kind,
            'scenario': str(meta['scenario']),
            'primary_label': meta.get('primary_label'),
            'secondary_label': meta.get('secondary_label'),
            'duration_ms': int(meta['duration_ms']),
            'sampled_frames': len(df),
            'quality_passed_frames': int(qp.sum()),
            'quality_rejected_frames': int((~qp).sum()),
            'camera_frames_seen': int(meta['camera_frames_seen']),
            'achieved_sample_fps': float(meta['achieved_sample_fps']),
            'median_pipeline_ms_metadata': float(meta['median_pipeline_ms']),
            'p95_pipeline_ms_metadata': float(meta['p95_pipeline_ms']),
            'target_5fps_capacity_ok_metadata': bool(meta['target_5fps_capacity_ok']),
            'model_sha256': str(meta['model_sha256']),
            'config_sha256': str(meta['config_sha256']),
            'frames_csv_sha256': str(meta['frames_csv_sha256']),
        })

    if duplicated_ids:
        raise RuntimeError(f'{root}: sequence_id duplikat: {duplicated_ids}')
    if schema_mismatches:
        raise RuntimeError(f'{root}: schema frames.csv berbeda: {schema_mismatches}')
    if hash_mismatches:
        raise RuntimeError(f'{root}: hash internal mismatch: {hash_mismatches[:3]}')
    if kinds != EXPECTED_COUNTS:
        raise RuntimeError(f'{root}: komposisi kind {kinds}, expected {EXPECTED_COUNTS}')
    if len(model_hashes) != 1 or len(config_hashes) != 1 or len(class_orders) != 1:
        raise RuntimeError(f'{root}: identitas model/config/class tidak konsisten antar sequence')
    if list(next(iter(class_orders))) != EXPECTED_CLASSES:
        raise RuntimeError(f'{root}: urutan kelas tidak sesuai')
    if not pipeline_quality_pass:
        raise RuntimeError(f'{root}: tidak ada quality-pass pipeline observation')

    p95 = float(np.percentile(np.asarray(pipeline_quality_pass, dtype=np.float64), 95))
    fmax = int(math.floor(1000.0 / p95))
    fp, file_hashes = directory_fingerprint(root, relevant_files)

    return {
        'root': str(root),
        'alias': expected_alias,
        'collector_config': cfg,
        'experiment_plan': plan,
        'inventory_rows': inventory_rows,
        'sequence_count': len(seq_dirs),
        'kind_counts': kinds,
        'total_sampled_frames': total_frames,
        'quality_passed_frames': total_qp,
        'quality_rejected_frames': total_qr,
        'quality_pass_pipeline_p95_ms': p95,
        'f_max_floor': fmax,
        'model_sha256': next(iter(model_hashes)),
        'config_sha256': next(iter(config_hashes)),
        'dataset_fingerprint_sha256': fp,
        'fingerprinted_files': file_hashes,
        'experiment_plan_sha256': sha256_file(root / 'experiment_plan.json'),
        'collector_config_sha256': sha256_file(root / 'collector_config.json'),
    }


def validate_android(android: Path, cfg_reference: Dict[str, Any]) -> Dict[str, Any]:
    app_config_path = android / 'app/src/main/assets/app_config.json'
    temporal_path = android / 'app/src/main/java/id/ac/ub/rupiah/prediction/TemporalDecision.kt'
    session_path = android / 'app/src/main/java/id/ac/ub/rupiah/session/RecognitionSession.kt'
    for p in [app_config_path, temporal_path, session_path]:
        if not p.is_file():
            raise FileNotFoundError(f'Android source tidak ditemukan: {p}')

    app = read_json(app_config_path)
    tol = 1e-5
    checks = {
        'roi_width_fraction': float(cfg_reference['roi_width_fraction']),
        'roi_aspect_ratio': float(cfg_reference['roi_aspect_ratio']),
        'blur_variance_min': float(cfg_reference['blur_variance_min']),
        'luma_min': float(cfg_reference['luma_min']),
        'luma_max': float(cfg_reference['luma_max']),
    }
    for k, expected in checks.items():
        actual = float(app[k])
        if abs(actual - expected) > tol:
            raise RuntimeError(f'Android app_config {k}={actual} berbeda dari collector={expected}')
    if bool(app['clahe_enabled']) != bool(cfg_reference['clahe_enabled']):
        raise RuntimeError('Android CLAHE berbeda dari collector')

    temporal = temporal_path.read_text(encoding='utf-8')
    session = session_path.read_text(encoding='utf-8')
    required_temporal_markers = [
        'window.clear() // Never reuse accepted evidence across an invalid image.',
        'labels[winner] == "nonuang"',
        'scores[winner] < config.threshold',
        'window.size <',
        'config.minimumResults',
        'best != winner',
        'label != announced',
        'now - rejectedSince!! >= config.windowMs',
    ]
    missing = [x for x in required_temporal_markers if x not in temporal]
    if missing:
        raise RuntimeError(f'TemporalDecision.kt semantics marker hilang: {missing}')
    if '(1000L + config.fps - 1) / config.fps' not in session:
        raise RuntimeError('RecognitionSession throttle formula tidak ditemukan')
    if 'decision?.markAnnounced(result.label)' not in session:
        raise RuntimeError('RecognitionSession markAnnounced tidak ditemukan')

    return {
        'app_config_path': str(app_config_path),
        'temporal_decision_path': str(temporal_path),
        'recognition_session_path': str(session_path),
        'app_config_sha256': sha256_file(app_config_path),
        'temporal_decision_sha256': sha256_file(temporal_path),
        'recognition_session_sha256': sha256_file(session_path),
        'app_config_status': app.get('status'),
        'postinference_status': app.get('postinference_status'),
        'current_development_values': {
            'analysis_fps': int(app['analysis_fps']),
            'confidence_threshold': float(app['confidence_threshold']),
            'temporal_window_ms': int(app['temporal_window_ms']),
            'minimum_results': int(app['minimum_results']),
        }
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--poco', type=Path, required=True)
    ap.add_argument('--redmi', type=Path, required=True)
    ap.add_argument('--android', type=Path, required=True)
    ap.add_argument('--plan', type=Path, default=Path(__file__).with_name('analysis_plan.json'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    plan = read_json(args.plan)
    poco = validate_source(args.poco, 'poco')
    redmi = validate_source(args.redmi, 'redmi_4x_santoni')

    if poco['experiment_plan_sha256'] != redmi['experiment_plan_sha256']:
        raise RuntimeError('experiment_plan.json POCO dan Redmi tidak identik')
    if poco['model_sha256'] != redmi['model_sha256']:
        raise RuntimeError('model SHA POCO dan Redmi berbeda')
    if poco['config_sha256'] != redmi['config_sha256']:
        raise RuntimeError('collector config identity POCO dan Redmi berbeda')

    android = validate_android(args.android, poco['collector_config'])

    candidates = [int(x) for x in plan['candidate_analysis_fps']]
    common_fmax = min(poco['f_max_floor'], redmi['f_max_floor'])
    feasible = [x for x in candidates if x <= common_fmax]
    if not feasible:
        raise RuntimeError(f'Tidak ada kandidat FPS yang <= common f_max={common_fmax}')
    selected_fps = max(feasible)

    inventory = pd.DataFrame(poco['inventory_rows'] + redmi['inventory_rows']).sort_values(['device','sequence_id'])
    capacity = pd.DataFrame([
        {'device':'poco','quality_pass_inference_frames':poco['quality_passed_frames'],'p95_pipeline_ms':poco['quality_pass_pipeline_p95_ms'],'f_max_floor':poco['f_max_floor'],'candidate_3_feasible':3<=poco['f_max_floor'],'candidate_5_feasible':5<=poco['f_max_floor']},
        {'device':'redmi_4x_santoni','quality_pass_inference_frames':redmi['quality_passed_frames'],'p95_pipeline_ms':redmi['quality_pass_pipeline_p95_ms'],'f_max_floor':redmi['f_max_floor'],'candidate_3_feasible':3<=redmi['f_max_floor'],'candidate_5_feasible':5<=redmi['f_max_floor']},
    ])

    audit = {
        'status': 'ready_for_postinference_replay',
        'analysis_plan_sha256': sha256_file(args.plan),
        'source_summary': {
            'poco': {k:v for k,v in poco.items() if k not in ['inventory_rows','experiment_plan','collector_config','fingerprinted_files']},
            'redmi_4x_santoni': {k:v for k,v in redmi.items() if k not in ['inventory_rows','experiment_plan','collector_config','fingerprinted_files']},
        },
        'shared_model_sha256': poco['model_sha256'],
        'shared_collector_config_identity_sha256': poco['config_sha256'],
        'shared_experiment_plan_sha256': poco['experiment_plan_sha256'],
        'android_reference': android,
        'fps_selection': {
            'candidate_fps': candidates,
            'common_f_max_floor': common_fmax,
            'feasible_candidates': feasible,
            'selected_analysis_fps': selected_fps,
            'rule': plan['fps_selection']['rule'],
        },
        'total_sequences': 80,
        'total_sampled_frames': poco['total_sampled_frames'] + redmi['total_sampled_frames'],
        'total_quality_passed_frames': poco['quality_passed_frames'] + redmi['quality_passed_frames'],
        'total_quality_rejected_frames': poco['quality_rejected_frames'] + redmi['quality_rejected_frames'],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    inv_path = args.out / 'sequence_inventory.csv'
    cap_path = args.out / 'fps_capacity_by_device.csv'
    audit_path = args.out / 'sequence_input_audit.json'
    inventory.to_csv(inv_path, index=False)
    capacity.to_csv(cap_path, index=False)
    write_json(audit_path, audit)

    lock = {
        'status': 'sequence_inputs_locked',
        'analysis_plan_sha256': sha256_file(args.plan),
        'input_fingerprints': {
            'poco': poco['dataset_fingerprint_sha256'],
            'redmi_4x_santoni': redmi['dataset_fingerprint_sha256'],
        },
        'android_source_hashes': {
            'app_config.json': android['app_config_sha256'],
            'TemporalDecision.kt': android['temporal_decision_sha256'],
            'RecognitionSession.kt': android['recognition_session_sha256'],
        },
        'selected_analysis_fps': selected_fps,
        'output_sha256': {
            'sequence_inventory.csv': sha256_file(inv_path),
            'fps_capacity_by_device.csv': sha256_file(cap_path),
            'sequence_input_audit.json': sha256_file(audit_path),
        }
    }
    write_json(args.out / 'sequence_input_lock.json', lock)

    print(json.dumps(audit['fps_selection'], indent=2))
    print(f"POCO P95={poco['quality_pass_pipeline_p95_ms']:.6f} ms -> f_max={poco['f_max_floor']}")
    print(f"Redmi P95={redmi['quality_pass_pipeline_p95_ms']:.6f} ms -> f_max={redmi['f_max_floor']}")
    print(f"selected_analysis_fps={selected_fps}")
    print('VALIDATION_STATUS=READY_FOR_POSTINFERENCE_REPLAY')
    print(f'Wrote: {args.out}')


if __name__ == '__main__':
    main()
