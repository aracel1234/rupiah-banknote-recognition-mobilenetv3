#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--result-dir', type=Path, required=True)
    args = ap.parse_args()

    lock_path = args.result_dir / 'postinference_calibration_lock.json'
    if not lock_path.is_file():
        raise FileNotFoundError(lock_path)
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    mismatches = []
    for name, expected in lock.get('output_sha256', {}).items():
        p = args.result_dir / name
        if not p.is_file():
            mismatches.append(f'{name}: missing')
            continue
        actual = sha256_file(p)
        if actual != expected:
            mismatches.append(f'{name}: expected={expected} actual={actual}')
    if mismatches:
        raise RuntimeError('Output verification failed:\n' + '\n'.join(mismatches))

    selected = lock['selected_postinference']
    print('OUTPUT_HASH_STATUS=OK')
    print(f"analysis_fps={selected['analysis_fps']}")
    print(f"confidence_threshold={selected['confidence_threshold']}")
    print(f"temporal_window_ms={selected['temporal_window_ms']}")
    print(f"minimum_results={selected['minimum_results']}")
    print('REVIEW_STATUS=READY_TO_SEND_FOR_AUDIT')


if __name__ == '__main__':
    main()
