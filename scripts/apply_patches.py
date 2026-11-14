#!/usr/bin/env python3
"""Validate/apply the recorded patch series to the exact pinned Chromium base."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args, data=None):
    return subprocess.check_output(['git', '-C', str(ROOT/'src'), *args],
                                   input=data).decode().strip()


def patch_id(data):
    output = subprocess.check_output(['git', 'patch-id', '--stable'], input=data)
    if not output.strip():
        raise RuntimeError('Patch has no changes')
    return output.decode().split()[0]


def validate_series():
    names = [n.strip() for n in (ROOT/'patches/series').read_text().splitlines()
             if n.strip() and not n.startswith('#')]
    if not names or len(names) != len(set(names)):
        raise RuntimeError('Patch series is empty or contains duplicate entries')
    patches = []
    for name in names:
        if Path(name).name != name or not name.endswith('.patch'):
            raise RuntimeError('Invalid patch filename: '+name)
        data = (ROOT/'patches'/name).read_bytes()
        patches.append((name, data, patch_id(data)))
    return patches


def run(apply=False):
    lock = json.loads((ROOT/'chromium.lock.json').read_text())
    patches = validate_series()
    if git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Chromium has uncommitted changes; commit/export them first')
    base = lock['revision']
    if git('rev-parse', 'HEAD') != base:
        subprocess.run(['git', '-C', str(ROOT/'src'), 'merge-base',
                        '--is-ancestor', base, 'HEAD'], check=True)
        commits = git('rev-list', '--reverse', base+'..HEAD').splitlines()
        ids = [patch_id(subprocess.check_output(['git', '-C', str(ROOT/'src'),
                    'show', '--format=', '--binary', c])) for c in commits]
        if ids != [p[2] for p in patches]:
            raise RuntimeError('Local commits differ from the exported patch series')
        print('PATCH CHECK PASSED: pinned Chromium base and all recorded patches match.')
        return
    if not apply:
        raise RuntimeError('Patches are not applied; run scripts/apply_patches.py --apply')
    branch = git('branch', '--show-current')
    if branch != 'alula':
        if git('branch', '--list', 'alula'):
            raise RuntimeError('An existing alula branch needs manual inspection; refusing to replace it')
        subprocess.run(['git', '-C', str(ROOT/'src'), 'switch', '-c', 'alula'], check=True)
    # git am preserves the original customization commit and author.
    subprocess.run(['git', '-C', str(ROOT/'src'), 'am',
                    *[str(ROOT/'patches'/p[0]) for p in patches]], check=True)
    run(False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        run(args.apply)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc)+'\n')
