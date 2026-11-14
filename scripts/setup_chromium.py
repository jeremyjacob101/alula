#!/usr/bin/env python3
"""Check an existing checkout, or explicitly fetch a fresh pinned checkout."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_alula as guard
from apply_patches import run as check_patches


def fetch():
    if sys.platform != 'darwin' or guard.command(['/usr/bin/uname', '-m']) != 'arm64':
        raise RuntimeError('This configuration currently supports Apple Silicon macOS only')
    if ' ' in str(ROOT):
        raise RuntimeError('Chromium requires a checkout path without spaces')
    if (ROOT/'src').exists():
        raise RuntimeError('src already exists. Use --check; existing checkouts are never reset by this script.')
    guard.command(['/usr/bin/xcodebuild', '-version'])
    guard.command(['/usr/bin/xcrun', 'metal', '--version'], timeout=30)
    pressure, swap = guard.memory()
    initial_free = guard.disk_free()
    if initial_free < 75*guard.GB or pressure == 4 or swap >= guard.MAX_SWAP:
        raise RuntimeError('Need at least 75 GB immediately free, noncritical memory pressure, and under 4 GB swap')
    lock = json.loads((ROOT/'chromium.lock.json').read_text())
    logs = ROOT/'build-logs'
    logs.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['PATH'] = str(ROOT/'depot_tools')+':'+str(ROOT/'depot_tools/python-bin')+':'+env['PATH']
    env['DEPOT_TOOLS_UPDATE'] = '0'
    env['PYTHONUNBUFFERED'] = '1'

    def stage(args, cwd=ROOT):
        print('SETUP:', ' '.join(map(str, args)), flush=True)
        with (logs/'setup.log').open('a') as log:
            process = subprocess.Popen(list(map(str, args)), cwd=cwd, env=env,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            known = {}
            started = time.monotonic()
            next_report = 0
            try:
                while process.poll() is None:
                    guard.track(process.pid, known, guard.processes())
                    pressure, swap = guard.memory()
                    free = guard.disk_free()
                    if (free < 25*guard.GB or initial_free-free > 50*guard.GB
                            or pressure == 4 or swap >= guard.MAX_SWAP
                            or time.monotonic()-started > 2*3600):
                        raise RuntimeError('Setup resource/time guard triggered; inspect build-logs/setup.log')
                    if guard.STOP_REQUEST:
                        raise RuntimeError(guard.STOP_REQUEST)
                    if time.monotonic() >= next_report:
                        print(f'SETUP MONITOR: free {free/guard.GB:.1f} GB; swap {swap/guard.GB:.2f} GB; pressure {pressure}', flush=True)
                        next_report = time.monotonic()+30
                    time.sleep(2)
                if process.wait():
                    tail = (logs/'setup.log').read_text(errors='replace').splitlines()[-15:]
                    raise RuntimeError('Setup command failed:\n'+'\n'.join(tail))
            finally:
                if process.poll() is None:
                    guard.terminate_tree(process, known)

    with (logs/'build.lock').open('a') as file:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, guard.signal_stop)
        awake = subprocess.Popen(['/usr/bin/caffeinate', '-is', '-w', str(os.getpid())])
        try:
            tools = ROOT/'depot_tools'
            if not tools.exists():
                stage(['git', 'clone', lock['depot_tools_repository'], str(tools)])
            if guard.command(['git', '-C', str(tools), 'remote', 'get-url', 'origin']) != lock['depot_tools_repository']:
                raise RuntimeError('Unexpected depot_tools origin; refusing to change it')
            stage(['git', 'checkout', '--detach', lock['depot_tools_revision']], cwd=tools)
            stage(['./ensure_bootstrap'], cwd=tools)
            stage(['gclient', 'config', '--unmanaged', lock['repository']])
            stage(['gclient', 'sync', '--no-history', '--nohooks', '--revision',
                   'src@refs/tags/'+lock['version'], '--jobs', '4'])
            actual = guard.command(['git', '-C', str(ROOT/'src'), 'rev-parse', 'HEAD'])
            if actual != lock['revision']:
                raise RuntimeError('Fetched version does not match pinned revision')
            stage(['gclient', 'runhooks'])
            stage([sys.executable, ROOT/'scripts/apply_patches.py', '--apply'])
            output = ROOT/'src/out/Alula'
            output.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/'config/args.gn', output/'args.gn')
            stage(['buildtools/mac/gn', 'gen', 'out/Alula', '--fail-on-unused-args'], cwd=ROOT/'src')
        finally:
            awake.terminate()
            awake.wait()
    print('SETUP COMPLETE. Chromium has not been compiled. Run python3 build_alula.py --check.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Validate existing source and build configuration; no downloads')
    group.add_argument('--fetch', action='store_true', help='Download dependencies for a fresh checkout; never compile Chromium')
    args = parser.parse_args()
    try:
        if args.check:
            check_patches(False)
            if (ROOT/'config/args.gn').read_bytes() != (ROOT/'src/out/Alula/args.gn').read_bytes():
                raise RuntimeError('Local build settings differ from config/args.gn')
            guard.preflight()
            print('SOURCE REPO CHECK PASSED. No downloads or compilation.')
        else:
            fetch()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc)+'\n')
