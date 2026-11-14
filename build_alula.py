#!/usr/bin/env python3
"""Compile Alula with resource guards. --check and --self-test never compile."""
import argparse
import datetime
import fcntl
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
OUT = SRC / 'out/Alula'
GB = 1_000_000_000
MIN_FREE = 25 * GB
MAX_OUTPUT = 75 * GB
MAX_SWAP = 4 * GB
MAX_SECONDS = 12 * 3600
STOP_REQUEST = None


def command(args, timeout=10):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT,
                                   timeout=timeout).strip()


def disk_free():
    st = os.statvfs(ROOT)
    return st.f_bavail * st.f_frsize


def memory():
    text = command(['/usr/sbin/sysctl', 'vm.swapusage',
                    'kern.memorystatus_vm_pressure_level'])
    pressure = re.search(r'kern.memorystatus_vm_pressure_level:\s*(\d+)', text)
    swap = re.search(r'used\s*=\s*([\d.]+)([KMGT])', text)
    if not pressure or not swap:
        raise RuntimeError('Cannot read memory pressure and swap; refusing unmonitored build')
    level = int(pressure.group(1))
    if level not in (1, 2, 4):
        raise RuntimeError('Unrecognized memory pressure level: ' + str(level))
    return level, float(swap.group(1)) * 1024 ** ('KMGT'.index(swap.group(2)) + 1)


def processes():
    text = command(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,rss=,stat=,lstart='])
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 10:
            pid, parent, group, rss = map(int, parts[:4])
            result[pid] = dict(parent=parent, group=group, rss=rss * 1024,
                               state=parts[4], identity=' '.join(parts[5:]))
    if not result:
        raise RuntimeError('Cannot inspect build processes')
    return result


def track(root_pid, known, table):
    selected = {root_pid}
    selected.update(pid for pid, identity in known.items()
                    if pid in table and table[pid]['identity'] == identity)
    while True:
        more = {pid for pid, p in table.items() if p['parent'] in selected}
        if more <= selected:
            break
        selected |= more
    for pid in selected:
        if pid in table:
            known[pid] = table[pid]['identity']
    return selected


def terminate_tree(proc, known):
    """Stop only the owned build tree, including descendants with new sessions."""
    try:
        _terminate_tree(proc, known)
    finally:
        # Even if process inspection itself fails, kill the isolated build group.
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)


def _terminate_tree(proc, known):
    # Freeze parents before killing descendants so they cannot spawn replacements.
    for _ in range(3):
        table = processes()
        selected = track(proc.pid, known, table)
        for pid in selected:
            if pid in table and table[pid]['identity'] == known.get(pid):
                try:
                    os.kill(pid, signal.SIGSTOP)
                except ProcessLookupError:
                    pass
        time.sleep(0.05)
    table = processes()
    selected = track(proc.pid, known, table)
    for pid in sorted(selected - {proc.pid}) + [proc.pid]:
        if pid in table and table[pid]['identity'] == known.get(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    # Owned descendants and the parent were killed above. Reap the parent
    # before fallback cleanup; macOS may return EPERM for a dead process group.
    proc.wait(timeout=10)


def size_of_output():
    return int(command(['/usr/bin/du', '-sk', str(OUT)], timeout=60).split()[0]) * 1024


def resource_reason(free, output, swap):
    if free < MIN_FREE:
        return 'Free disk space fell below 25 GB'
    if output >= MAX_OUTPUT:
        return 'Build output folder reached 75 GB'
    if swap >= MAX_SWAP:
        return 'System swap reached 4 GB'
    return None


def preflight():
    if not (OUT / 'build.ninja').is_file():
        raise RuntimeError('Configured build files are missing')
    try:
        command(['/usr/bin/xcrun', 'metal', '--version'], timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Metal Toolchain is unavailable. Run: '
                           'xcodebuild -downloadComponent MetalToolchain '
                           'and then rerun --check.') from error
    expected = {'target_cpu': '"arm64"', 'is_debug': 'false',
                'is_component_build': 'true', 'symbol_level': '0',
                'use_remoteexec': 'false'}
    args = (OUT / 'args.gn').read_text()
    for name, value in expected.items():
        if not re.search(r'^' + name + r'\s*=\s*' + re.escape(value) + r'\s*$', args, re.M):
            raise RuntimeError('Unexpected build setting: ' + name)
    branch = command(['git', '-C', str(SRC), 'branch', '--show-current'])
    if branch != 'alula':
        raise RuntimeError('Expected alula branch; found ' + branch)
    pressure, swap = memory()
    free = disk_free()
    size = size_of_output()
    processes()
    reason = resource_reason(free, size, swap)
    if pressure == 4:
        reason = 'Memory pressure is already critical'
    if reason:
        raise RuntimeError(reason)
    print(f'CHECK PASSED: free {free / GB:.1f} GB; output {size / GB:.2f} GB; '
          f'pressure { {1: "normal", 2: "warning", 4: "critical"}[pressure] }; '
          f'swap {swap / GB:.2f} GB', flush=True)
    print('GUARDS: 25 GB free-space floor; 75 GB output-folder cap; 4 GB swap cap; '
          'critical memory for 15 seconds; 12-hour time limit; 4 compiler jobs.', flush=True)
    return size


def self_test():
    assert resource_reason(MIN_FREE - 1, 0, 0)
    assert resource_reason(MIN_FREE + 1, MAX_OUTPUT, 0)
    assert resource_reason(MIN_FREE + 1, 0, MAX_SWAP)
    assert resource_reason(MIN_FREE + 1, 0, 0) is None
    code = ('import subprocess,sys,time; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"],start_new_session=True); '
            'print(p.pid,flush=True); time.sleep(120)')
    p = subprocess.Popen([sys.executable, '-u', '-c', code],
                         stdout=subprocess.PIPE, text=True, start_new_session=True)
    known = {}
    try:
        child = int(p.stdout.readline())
        track(p.pid, known, processes())
        assert child in known, 'Test descendant was not tracked'
        terminate_tree(p, known)
        table = processes()
        for pid, identity in known.items():
            assert pid not in table or table[pid]['identity'] != identity or table[pid]['state'].startswith('Z'), 'Test process survived stop'
    finally:
        if p.poll() is None:
            terminate_tree(p, known)
        p.stdout.close()
    print('SELF-TEST PASSED: disk/output/swap cutoffs and process-tree kill '
          '(including a child in a separate session). No Chromium compilation.', flush=True)


def signal_stop(sig, frame):
    global STOP_REQUEST
    STOP_REQUEST = 'Received ' + signal.Signals(sig).name


def build():
    size = preflight()
    logroot = ROOT / 'build-logs'
    logroot.mkdir(exist_ok=True)
    with (logroot / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another guarded build is already running')
        run = logroot / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        run.mkdir()
        latest = logroot / 'latest'
        if latest.exists() and not latest.is_symlink():
            raise RuntimeError('build-logs/latest exists and is not a symlink')
        latest.unlink(missing_ok=True)
        latest.symlink_to(run.name)
        env = os.environ.copy()
        env['PATH'] = str(ROOT / 'depot_tools') + ':' + str(ROOT / 'depot_tools/python-bin') + ':' + env['PATH']
        env['DEPOT_TOOLS_UPDATE'] = '0'
        env['PYTHONUNBUFFERED'] = '1'
        cmd = [str(ROOT / 'depot_tools/autoninja'), '-C', 'out/Alula', '-j', '4', 'chrome']
        proc = None
        awake = None
        scan = None
        known = {}
        started = time.monotonic()
        critical_since = None
        next_scan = 0
        next_report = 0
        state = 'STOPPED'
        reason = 'Launcher did not finish'
        old_handlers = {}
        with (run / 'monitor.log').open('a', buffering=1) as monitor, (run / 'build.log').open('w', buffering=1) as log:
            def report(message):
                stamp = datetime.datetime.now().strftime('%H:%M:%S')
                text = f'[{stamp}] {message}'
                print(text, flush=True)
                monitor.write(text + '\n')
                temp = run / 'status.tmp'
                temp.write_text(text + '\n')
                temp.replace(run / 'status.txt')
            try:
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    old_handlers[sig] = signal.signal(sig, signal_stop)
                report('GUARDS ARMED. Starting compilation with 4 jobs. Logs: ' + str(run))
                reason = None
                proc = subprocess.Popen(cmd, cwd=SRC, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
                awake = subprocess.Popen(['/usr/bin/caffeinate', '-is', '-w', str(proc.pid)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while proc.poll() is None:
                    now = time.monotonic()
                    table = processes()
                    selected = track(proc.pid, known, table)
                    pressure, swap = memory()
                    free = disk_free()
                    if scan is None and now >= next_scan:
                        scan = subprocess.Popen(['/usr/bin/du', '-sk', str(OUT)],
                                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        scan_started = now
                    if scan is not None and scan.poll() is not None:
                        output, error = scan.communicate()
                        if scan.returncode:
                            raise RuntimeError('Build-size measurement failed: ' + error)
                        size = int(output.split()[0]) * 1024
                        scan = None
                        next_scan = now + 10
                    if scan is not None and now - scan_started > 60:
                        raise RuntimeError('Build-size monitoring timed out')
                    if pressure == 4:
                        critical_since = critical_since or now
                    else:
                        critical_since = None
                    reason = STOP_REQUEST or resource_reason(free, size, swap)
                    if critical_since is not None and now - critical_since >= 15:
                        reason = 'Memory pressure remained critical for 15 seconds'
                    if now - started >= MAX_SECONDS:
                        reason = '12-hour build time limit reached'
                    if reason:
                        report('STOPPING: ' + reason)
                        terminate_tree(proc, known)
                        break
                    if now >= next_report:
                        rss = sum(table[pid]['rss'] for pid in selected if pid in table)
                        label = {1: 'normal', 2: 'warning', 4: 'critical'}[pressure]
                        report(f'RUNNING: {int((now-started)/60)} min; free {free/GB:.1f} GB; '
                               f'build folder {size/GB:.2f} GB; memory {label}; swap {swap/GB:.2f} GB; '
                               f'build RSS sum {rss/GB:.2f} GB (shared memory may be counted twice)')
                        next_report = now + 30
                    time.sleep(2)
                code = proc.wait()
                if reason:
                    state = 'STOPPED'
                elif code == 0:
                    if not (OUT / 'alula.app/Contents/MacOS/alula').is_file():
                        raise RuntimeError('Build exited successfully but alula executable is missing')
                    state, reason = 'SUCCESS', 'alula compiled. Browser was not launched.'
                else:
                    state, reason = 'FAILED', f'Build exited {code}; inspect build.log'
            except BaseException as exc:
                reason = str(exc) or type(exc).__name__
                if proc is not None and proc.poll() is None:
                    terminate_tree(proc, known)
                state = 'STOPPED'
            finally:
                if scan is not None:
                    scan.terminate()
                    scan.communicate()
                if awake is not None:
                    awake.terminate()
                    awake.wait()
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
                report(state + ': ' + str(reason))
        return 0 if state == 'SUCCESS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument('--check', action='store_true', help='Check readiness; never compile')
    options.add_argument('--self-test', action='store_true', help='Test guard logic; never compile')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.check:
        preflight()
        print('READY. No compilation started.')
        return 0
    return build()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('REFUSED / ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
