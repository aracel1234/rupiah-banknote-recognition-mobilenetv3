#!/usr/bin/env python3
"""Copy only the locked stage-7 winner. Never edits any stage-1..7 source/output."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

EXPECTED = 'fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676'
CLASSES = ['1000', '2000', '5000', '10000', '20000', '50000', '100000', 'nonuang']
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage7', type=Path, required=True, help='Folder 07_compare, bukan folder final_assets')
    args = parser.parse_args()
    source = args.stage7.resolve()
    assets = source / 'final_assets'
    lock = read(source / 'selection_lock.json')
    latest = read(source / 'latest.json')
    contract = read(assets / 'tensor_contract.json')
    identity = read(assets / 'model_identity.json')
    model_hash = digest(assets / 'model.tflite')
    if not (latest['status'] == 'complete' and latest['selected_candidate'] == lock['selected_candidate'] == 'dynamic_range'
            and latest['selection_lock_sha256'] == digest(source / 'selection_lock.json')
            and model_hash == EXPECTED == latest['selected_model_sha256'] == lock['model_sha256']
            == contract['model_sha256'] == identity['sha256'] == identity['source_stage6_sha256']):
        raise ValueError('Sumber tidak cocok dengan model terpilih yang dikaji untuk proyek ini.')
    if read(assets / 'class_names.json') != CLASSES or contract['class_names'] != CLASSES:
        raise ValueError('Urutan kelas berbeda.')
    if digest(assets / 'class_names.json') != lock['class_names_sha256']:
        raise ValueError('Hash label berbeda.')
    if not (contract['input_shape'] == [1, 224, 224, 3] and contract['output_shape'] == [1, 8]
            and contract['input_dtype'] == contract['output_dtype'] == 'float32'):
        raise ValueError('Kontrak tensor berbeda.')
    destination = Path(__file__).resolve().parents[1] / 'app/src/main/assets/model'
    destination.mkdir(parents=True, exist_ok=True)
    names = ['model.tflite', 'class_names.json', 'tensor_contract.json', 'model_identity.json']
    for name in names: shutil.copy2(assets / name, destination / name)
    shutil.copy2(source / 'selection_lock.json', destination / 'selection_lock.json')
    manifest = {name: digest(destination / name) for name in names + ['selection_lock.json']}
    (destination / 'asset_integrity.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Aset model terpilih siap:', destination)
    print('SHA-256:', model_hash)
if __name__ == '__main__': main()
