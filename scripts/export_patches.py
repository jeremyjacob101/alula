#!/usr/bin/env python3
"""Export committed alula changes above the pinned Chromium base."""
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT/'chromium.lock.json').read_text())
    git = ['git', '-C', str(ROOT/'src')]
    if subprocess.check_output(git+['status', '--porcelain', '--untracked-files=no']).strip():
        raise RuntimeError('Commit your Chromium changes before exporting')
    subprocess.run(git+['merge-base', '--is-ancestor', lock['revision'], 'HEAD'], check=True)
    count = int(subprocess.check_output(git+['rev-list', '--count', lock['revision']+'..HEAD']))
    if not 1 <= count <= 200:
        raise RuntimeError('Expected 1–200 local commits; inspect the base revision')
    with tempfile.TemporaryDirectory(prefix='alula-patches-') as temp:
        subprocess.run(git+['format-patch', '--no-signature', '--output-directory', temp,
                            lock['revision']+'..HEAD'], check=True)
        files = sorted(Path(temp).glob('*.patch'))
        if len(files) != count:
            raise RuntimeError('Unexpected patch count')
        destination = ROOT/'patches'
        # Existing patches not listed in series are harmless and left untouched.
        for file in files:
            (destination/file.name).write_bytes(file.read_bytes())
        (destination/'series').write_text(''.join(p.name+'\n' for p in files))
    lock['patch_commit'] = subprocess.check_output(git+['rev-parse', 'HEAD']).decode().strip()
    (ROOT/'chromium.lock.json').write_text(json.dumps(lock, indent=2)+'\n')
    print('Exported', count, 'patch(es). Review the parent alula repo diff before committing.')


if __name__ == '__main__':
    main()
