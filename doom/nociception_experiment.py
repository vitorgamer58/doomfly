"""Automated Milestone 4 experiment: one brain per damage-input condition, then the analysis.

Every condition starts the same calibrated v6 brain with frozen weights, the
same ViZDoom seed and the same random-population seed, runs for a fixed neural
time in the combat arena and stops cleanly. Conditions run in parallel only
while enough physical memory stays free. Completed conditions are skipped on
restart; an interrupted attempt is kept under a separate name, never mixed
into the next attempt.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ['none', 'snxx29', 'random-matched', 'random-dose-matched', 'ppl101']
RANDOM = ('random-matched', 'random-dose-matched')


def command(condition, directory, *, port, neural_seconds, seed, nociception_seed, learning=False,
            checkpoint_seconds=None, python=sys.executable):
    cmd = [python, '-m', 'doom.server', '--model', 'experimental-v6', '--damage-input', condition,
           '--seed', str(seed), '--port', str(port), '--bind', '127.0.0.1', '--audit-dir', str(directory),
           '--max-neural-seconds', str(neural_seconds)]
    if condition in RANDOM:
        cmd += ['--nociception-seed', str(nociception_seed)]
    if learning:
        # Milestone 6+: plasticity on, one continuous brain across every death.
        cmd += ['--learning']
    if checkpoint_seconds:
        cmd += ['--checkpoint-dir', str(Path(directory)/'checkpoints'), '--resume',
                '--checkpoint-seconds', str(checkpoint_seconds)]
    return cmd


def completed(directory):
    for path in Path(directory).glob('run-*-end.json'):
        try:
            if json.loads(path.read_text()).get('end_reason') == 'max-neural-seconds':
                return True
        except ValueError:
            continue
    return False


def prepare_directory(directory):
    """Move an unfinished attempt aside so a new attempt starts clean."""
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()) and not completed(directory):
        target = directory.with_name(f'{directory.name}.incomplete-{time.strftime("%Y%m%dT%H%M%S")}')
        directory.rename(target)
        return target
    return None


def free_memory_gb():
    try:
        import psutil
        return psutil.virtual_memory().available/1024**3
    except ImportError:
        pass
    if sys.platform == 'win32':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ['total_phys', 'avail_phys', 'total_page', 'avail_page',
                                                         'total_virtual', 'avail_virtual', 'avail_extended']]
        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.avail_phys/1024**3
    with open('/proc/meminfo') as f:
        for line in f:
            if line.startswith('MemAvailable:'):
                return int(line.split()[1])/1024**2
    return float('inf')


def progress(directory):
    lives = Path(directory)/'lives.jsonl'
    count = sum(1 for _ in lives.open()) if lives.exists() else 0
    return {'lives_logged': count}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', default=str(ROOT/'outputs/doom/nociception/m4-v1'))
    p.add_argument('--conditions', default=','.join(CONDITIONS))
    p.add_argument('--neural-seconds', type=float, default=600.)
    p.add_argument('--seed', type=int, default=41027)
    p.add_argument('--nociception-seed', type=int, default=41027)
    p.add_argument('--max-jobs', type=int, default=5)
    p.add_argument('--min-free-gb', type=float, default=3.5, help='Start another brain only above this free memory')
    p.add_argument('--settle-seconds', type=float, default=150., help='Wait after each start so its memory is visible')
    p.add_argument('--base-port', type=int, default=8810)
    p.add_argument('--learning', action='store_true', help='Milestone 6+: enable the v6 KC-to-MBON11 plasticity')
    p.add_argument('--checkpoint-seconds', type=int,
                   help='Checkpoint each brain this often and resume it in place after an interruption')
    p.add_argument('--analysis-only', action='store_true')
    args = p.parse_args()
    conditions = args.conditions.split(',')
    if not set(conditions) <= set(CONDITIONS):
        p.error(f'Conditions must be among {CONDITIONS}')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out/'experiment.json').write_text(json.dumps({'schema': 1, 'milestone': 6 if args.learning else 4,
        'arguments': vars(args), 'weights_frozen': not args.learning, 'reward': 'off',
        'model': 'experimental-v6', 'started_at_ms': int(time.time()*1000)}, indent=2)+'\n')

    failures = {}
    if not args.analysis_only:
        pending = [c for c in conditions if not completed(out/c)]
        running = {}
        last_start = -args.settle_seconds
        last_report = time.monotonic()
        while pending or running:
            for condition, (process, log, began) in list(running.items()):
                code = process.poll()
                if code is None:
                    continue
                log.close()
                del running[condition]
                ok = code == 0 and completed(out/condition)
                print(json.dumps({'condition': condition, 'exit': code, 'completed': ok,
                                  'wall_minutes': round((time.monotonic() - began)/60, 1)}), flush=True)
                if not ok:
                    failures[condition] = code
            now = time.monotonic()
            if (pending and len(running) < args.max_jobs and now - last_start >= args.settle_seconds
                    and (not running or free_memory_gb() >= args.min_free_gb)):
                condition = pending.pop(0)
                directory = out/condition
                # With checkpoints the interrupted brain resumes in place instead.
                moved = None if args.checkpoint_seconds else prepare_directory(directory)
                directory.mkdir(parents=True, exist_ok=True)
                log = open(directory/'server.log', 'a')
                env = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
                cmd = command(condition, directory, port=args.base_port + CONDITIONS.index(condition),
                              neural_seconds=args.neural_seconds, seed=args.seed, nociception_seed=args.nociception_seed,
                              learning=args.learning, checkpoint_seconds=args.checkpoint_seconds)
                running[condition] = (subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env), log, now)
                last_start = now
                print(json.dumps({'started': condition, 'free_gb': round(free_memory_gb(), 2), 'running': sorted(running),
                                  'previous_attempt_moved_to': str(moved) if moved else None}), flush=True)
            if now - last_report >= 600:
                print(json.dumps({'progress': {c: progress(out/c) for c in running}, 'pending': pending,
                                  'free_gb': round(free_memory_gb(), 2)}), flush=True)
                last_report = now
            time.sleep(5)

    from doom.analyze_nociception import analyze
    runs = {c: out/c for c in conditions if completed(out/c)}
    if runs:
        report = analyze(runs)
        report['experiment'] = json.loads((out/'experiment.json').read_text())
        report['failed_conditions'] = failures
        (out/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
        for label, c in report['conditions'].items():
            print(json.dumps({'condition': label, 'damage_events': c['analyzed_events'], 'lives': c['lives']}), flush=True)
        print(out/'analysis.json')
    if failures or len(runs) != len(conditions):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
