#!/usr/bin/env python3
"""Record source/config/model identity without claiming calibration or system-test completion."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    project = Path(__file__).resolve().parents[1]
    config = json.loads((project / 'app/src/main/assets/app_config.json').read_text())
    wanted = []
    for path in project.rglob('*'):
        if not path.is_file() or path.resolve() == args.out.resolve(): continue
        rel = path.relative_to(project)
        if any(part in {'build', '.gradle', '.git', '.idea', '__pycache__'} for part in rel.parts): continue
        if path.name == 'local.properties' or path.suffix in {'.jks', '.keystore', '.zip'}: continue
        if rel.parts[0] == 'docs' and path.name.endswith('_snapshot.json'): continue
        wanted.append(path)
    hashes = {str(f.relative_to(project)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(wanted)}
    report = {'snapshot_utc': datetime.now(timezone.utc).isoformat(),
              'app_parameter_status': config['status'], 'system_testing_performed_by_this_script': False,
              'files': hashes}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Snapshot ditulis:', args.out)
if __name__ == '__main__': main()
