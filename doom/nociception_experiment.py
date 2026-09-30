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
from doom.nociception import RANDOM_SOURCES as RANDOM

CONDITIONS = ['none', 'snxx29', 'random-matched', 'random-dose-matched', 'ppl101']
# Milestone 4: no plasticity, one arm per damage_input, arm name == damage_input.
M4_ARMS = {c: {'damage_input': c, 'learning': False, 'reset_on_death': False} for c in CONDITIONS}
# Milestone 6 (task_atualizado.md section 25): plasticity on, one continuous brain per arm across
# every death. E is the only arm that resets dynamic neural state at death (Control E); F is a fresh
# no-learning run at the same duration, not a reuse of the Milestone 4 snxx29 run (different simulation_age
# pairing would confound any comparison).
M6_ARMS = {
    'A_snxx29': {'damage_input': 'snxx29', 'learning': True, 'reset_on_death': False},
    'B_random_dose_matched': {'damage_input': 'random-dose-matched', 'learning': True, 'reset_on_death': False},
    'C_none': {'damage_input': 'none', 'learning': True, 'reset_on_death': False},
    'D_ppl101': {'damage_input': 'ppl101', 'learning': True, 'reset_on_death': False},
    'E_snxx29_reset_on_death': {'damage_input': 'snxx29', 'learning': True, 'reset_on_death': True},
    'F_snxx29_no_learning': {'damage_input': 'snxx29', 'learning': False, 'reset_on_death': False},
}
PRESETS = {'m4': M4_ARMS, 'm6': M6_ARMS}


def command(arm, directory, *, port, neural_seconds, seed, nociception_seed, checkpoint_seconds=None, python=sys.executable):
    cmd = [python, '-m', 'doom.server', '--model', 'experimental-v6', '--damage-input', arm['damage_input'],
           '--seed', str(seed), '--port', str(port), '--bind', '127.0.0.1', '--audit-dir', str(directory),
           '--max-neural-seconds', str(neural_seconds)]
    if arm['damage_input'] in RANDOM:
        cmd += ['--nociception-seed', str(nociception_seed)]
    if arm['learning']:
        # Milestone 6+: plasticity on, one continuous brain across every death.
        cmd += ['--learning']
    if arm['reset_on_death']:
        cmd += ['--reset-on-death']
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


def simulated_seconds(directory):
    """Total neural time already logged for this arm, across every past process invocation.

    doom.server's --max-neural-seconds is per process, not a running total (a resume after an
    interruption starts a fresh budget from wherever the checkpoint left off). This orchestrator is
    the one place that has to make every arm converge on the same absolute target, so it computes the
    remaining budget itself before each (re)launch instead of always requesting the full duration.
    """
    path = Path(directory)/'lives.jsonl'
    if not path.exists():
        return 0.
    last = None
    for line in path.open():
        if line.strip():
            last = line
    return json.loads(last)['end_simulation_age_ms']/1000 if last else 0.


def mark_complete(directory):
    (Path(directory)/f'run-orchestrator-{time.strftime("%Y%m%dT%H%M%S")}-end.json').write_text(
        json.dumps({'end_reason': 'max-neural-seconds', 'note': 'Target already reached by a prior process; not relaunched.'})+'\n')


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
    p.add_argument('--preset', choices=list(PRESETS), default='m4', help='m4: frozen weights, one arm per damage_input. '
                   'm6: plasticity on, the six task_atualizado.md section-25 arms (A-F)')
    p.add_argument('--out')
    p.add_argument('--conditions', help='Comma-separated arm names to run; default is every arm in --preset')
    p.add_argument('--neural-seconds', type=float, default=600.)
    p.add_argument('--seed', type=int, default=41027)
    p.add_argument('--nociception-seed', type=int, default=41027)
    p.add_argument('--max-jobs', type=int, default=5)
    p.add_argument('--min-free-gb', type=float, default=3.5, help='Start another brain only above this free memory')
    p.add_argument('--settle-seconds', type=float, default=150., help='Wait after each start so its memory is visible')
    p.add_argument('--base-port', type=int, default=8810)
    p.add_argument('--checkpoint-seconds', type=int,
                   help='Checkpoint each brain this often and resume it in place after an interruption')
    p.add_argument('--analysis-only', action='store_true')
    args = p.parse_args()
    all_arms = PRESETS[args.preset]
    arm_names = args.conditions.split(',') if args.conditions else list(all_arms)
    if not set(arm_names) <= set(all_arms):
        p.error(f'--conditions must be among {list(all_arms)} for preset {args.preset!r}')
    if args.out is None:
        args.out = str(ROOT/f'outputs/doom/nociception/{args.preset}-v1')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    milestone = 4 if args.preset == 'm4' else 6
    (out/'experiment.json').write_text(json.dumps({'schema': 1, 'milestone': milestone, 'preset': args.preset,
        'arms': {n: all_arms[n] for n in arm_names}, 'arguments': vars(args),
        'reward': 'off', 'model': 'experimental-v6', 'started_at_ms': int(time.time()*1000)}, indent=2)+'\n')

    failures = {}
    if not args.analysis_only:
        pending = list(arm_names)
        pending = [n for n in pending if not completed(out/n)]
        running = {}
        last_start = -args.settle_seconds
        last_report = time.monotonic()
        while pending or running:
            for name, (process, log, began) in list(running.items()):
                code = process.poll()
                if code is None:
                    continue
                log.close()
                del running[name]
                ok = code == 0 and completed(out/name)
                print(json.dumps({'arm': name, 'exit': code, 'completed': ok,
                                  'wall_minutes': round((time.monotonic() - began)/60, 1)}), flush=True)
                if not ok:
                    failures[name] = code
            now = time.monotonic()
            if (pending and len(running) < args.max_jobs and now - last_start >= args.settle_seconds
                    and (not running or free_memory_gb() >= args.min_free_gb)):
                name = pending.pop(0)
                directory = out/name
                remaining = args.neural_seconds - simulated_seconds(directory)
                if remaining <= 0:
                    # A prior interrupted-and-resumed process already reached (or passed) the target.
                    mark_complete(directory)
                    print(json.dumps({'arm': name, 'already_at_target': True,
                                      'simulated_seconds': round(simulated_seconds(directory), 1)}), flush=True)
                    continue
                # With checkpoints the interrupted brain resumes in place instead.
                moved = None if args.checkpoint_seconds else prepare_directory(directory)
                directory.mkdir(parents=True, exist_ok=True)
                log = open(directory/'server.log', 'a')
                env = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
                cmd = command(all_arms[name], directory, port=args.base_port + list(all_arms).index(name),
                              neural_seconds=remaining, seed=args.seed, nociception_seed=args.nociception_seed,
                              checkpoint_seconds=args.checkpoint_seconds)
                running[name] = (subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env), log, now)
                last_start = now
                print(json.dumps({'started': name, 'remaining_neural_seconds': round(remaining, 1),
                                  'free_gb': round(free_memory_gb(), 2), 'running': sorted(running),
                                  'previous_attempt_moved_to': str(moved) if moved else None}), flush=True)
            if now - last_report >= 600:
                print(json.dumps({'progress': {n: progress(out/n) for n in running}, 'pending': pending,
                                  'free_gb': round(free_memory_gb(), 2)}), flush=True)
                last_report = now
            time.sleep(5)

    from doom.analyze_nociception import analyze
    runs = {n: out/n for n in arm_names if completed(out/n)}
    # Arms restarted after an interruption can end up with unequal total neural time (doom.server's
    # --max-neural-seconds is per process). Trim every arm to the common target so the comparison
    # across arms stays fair; any extra simulated time an arm accumulated is kept on disk, just
    # excluded from this comparison.
    cutoff_ms = args.neural_seconds*1000
    reference = next((n for n in arm_names if all_arms[n]['damage_input'] == 'none'), 'none')
    if runs:
        report = analyze(runs, max_simulation_age_ms=cutoff_ms, reference=reference)
        report['experiment'] = json.loads((out/'experiment.json').read_text())
        report['failed_conditions'] = failures
        (out/'analysis.json').write_text(json.dumps(report, indent=2)+'\n')
        for label, c in report['conditions'].items():
            print(json.dumps({'condition': label, 'damage_events': c['analyzed_events'], 'lives': c['lives']}), flush=True)
        print(out/'analysis.json')
        if milestone == 6:
            from doom.analyze_learning import analyze_learning
            curves = analyze_learning(runs, max_simulation_age_ms=cutoff_ms)
            (out/'learning-curves.json').write_text(json.dumps(curves, indent=2)+'\n')
            print(out/'learning-curves.json')
    if failures or len(runs) != len(arm_names):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
