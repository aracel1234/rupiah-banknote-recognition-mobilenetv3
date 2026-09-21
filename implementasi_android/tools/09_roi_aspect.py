#!/usr/bin/env python3
"""Calculate the actual median w/h from curated, deduplicated PNGs; not a calibration experiment."""
import argparse
import csv
import hashlib
import json
import statistics
import struct
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True, help='Folder persiapan_data')
    p.add_argument('--manifest', type=Path, help='Default: root/04_dedup/money_unique_manifest.csv')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    manifest = args.manifest or root / '04_dedup/money_unique_manifest.csv'
    with manifest.open(newline='', encoding='utf-8-sig') as stream: rows = list(csv.DictReader(stream))
    ratios = []; seen = set()
    for row in rows:
        if row.get('label') == 'nonuang': continue
        path = (root / row['file_path']).resolve()
        if not path.is_relative_to(root): raise ValueError('Path citra di luar root.')
        if path in seen: raise ValueError('File ganda dalam manifest.')
        seen.add(path)
        with path.open('rb') as stream: header = stream.read(24)
        if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
            raise ValueError(f'Bukan PNG hasil ekstraksi: {path}')
        w, h = struct.unpack('>II', header[16:24])
        if not w or not h: raise ValueError('Dimensi PNG tidak valid.')
        ratios.append(w / h)
    if not ratios: raise ValueError('Tidak ada citra uang.')
    report = {'status': 'dataset_geometry_only', 'samples': len(ratios),
              'roi_aspect_ratio': statistics.median(ratios),
              'formula': 'median(width / height), no automatic rotation',
              'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
if __name__ == '__main__': main()
