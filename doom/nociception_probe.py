"""Milestone 3: open-loop propagation probe for simulated nociception.

No Doom game runs and no action is applied. The complete calibrated v6 brain
(166,700 neurons, frozen weights) views one fixed frame. After equilibration a
single saved state seeds every arm, so arms differ only in which population is
driven: nothing (sham), SNxx29, or the matched random leg sensory control.

The simulation is deterministic. Arm differences are exact model responses for
this state, frame and transducer drive, not samples of biological variability,
and responses here do not establish that the fly would feel or avoid anything.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BIN_MS = 10
WINDOWS_MS = {'pre': (-200, 0), 'onset_0_50': (0, 50), 'pulse_50_200': (50, 200), 'after_200_1000': (200, 1000)}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def load_frame(path):
    if path is None:
        return np.full((480, 640, 3), 64, dtype=np.uint8)
    from PIL import Image
    return np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8).copy()


def onsets(pulses, first_ms, interval_ms, jitter_ms, rng):
    times, t = [], first_ms
    for _ in range(pulses):
        times.append(t)
        t += interval_ms + BIN_MS*int(rng.integers(0, jitter_ms//BIN_MS + 1))
    return times


def run_arm(brain, frame, groups, controls, *, indices, gain, starts, pulse_ms, total_ms):
    """Advance in 10 ms bins; return group spike counts per bin and decoded controls."""
    names = list(groups)
    bins = total_ms//BIN_MS
    spikes = np.zeros((bins, len(names)), dtype=np.int64)
    decoded = np.zeros((bins, 3), dtype=np.float64)
    controls.rates[:] = 0
    for b in range(bins):
        t = b*BIN_MS
        active = indices is not None and any(s <= t < s + pulse_ms for s in starts)
        c, _ = brain.rgb_step(frame, float(BIN_MS), learning=False, stimulation=(indices, gain) if active else None)
        spikes[b] = [int(c[groups[k]].sum()) for k in names]
        a = controls.decode(c, BIN_MS/1000)
        decoded[b] = [a['turn'], a['forward'], float(a['attack'])]
    return spikes, decoded


def pulse_rate(brain, state, frame, groups, controls, key, indices, gain, pulse_ms):
    """Population rate (Hz per cell) of ``groups[key]`` during one pulse from the saved state."""
    brain.restore(state)
    spikes, _ = run_arm(brain, frame, groups, controls, indices=indices, gain=gain,
                        starts=[100], pulse_ms=pulse_ms, total_ms=100 + pulse_ms)
    column = list(groups).index(key)
    return float(spikes[100//BIN_MS:, column].sum()/len(groups[key])/(pulse_ms/1000))


def calibrate_dose(brain, state, frame, groups, controls, snxx29, random, gain, pulse_ms):
    """Grid then refined search for the random-population gain matching the SNxx29 rate at ``gain``.

    The recurrent network is not guaranteed monotonic in drive, so every
    evaluated point is kept and the best observed point is chosen.
    """
    target = pulse_rate(brain, state, frame, groups, controls, 'SNxx29', snxx29, gain, pulse_ms)
    search = []
    def evaluate(g):
        rate = pulse_rate(brain, state, frame, groups, controls, 'random_matched', random, g, pulse_ms)
        search.append({'gain_mv': round(g, 4), 'random_rate_hz': round(rate, 4)})
        print(json.dumps(search[-1]), flush=True)
        return rate
    for g in np.arange(7., gain + 1e-9, 1.):
        evaluate(float(g))
    best = min(search, key=lambda s: abs(s['random_rate_hz'] - target))['gain_mv']
    for g in np.arange(best - .75, best + .76, .25):
        if g > 0 and all(abs(s['gain_mv'] - g) > 1e-6 for s in search):
            evaluate(float(g))
    chosen = min(search, key=lambda s: (abs(s['random_rate_hz'] - target), s['gain_mv']))
    return target, chosen, sorted(search, key=lambda s: s['gain_mv'])


def summarize(spikes, decoded, sham_spikes, sham_decoded, groups, starts):
    names = list(groups)
    out = {}
    for g, name in enumerate(names):
        n = max(1, len(groups[name]))
        windows = {}
        for label, (lo, hi) in WINDOWS_MS.items():
            per_pulse = []
            for s in starts:
                a, b = (s + lo)//BIN_MS, (s + hi)//BIN_MS
                seconds = (hi - lo)/1000
                arm = spikes[a:b, g].sum()/n/seconds
                sham = sham_spikes[a:b, g].sum()/n/seconds
                per_pulse.append(arm - sham)
            windows[label] = {'mean_rate_delta_hz_vs_sham': round(float(np.mean(per_pulse)), 4),
                              'min': round(float(np.min(per_pulse)), 4), 'max': round(float(np.max(per_pulse)), 4)}
        latencies = []
        for s in starts:
            a = s//BIN_MS
            diff = spikes[a:a + 100, g] - sham_spikes[a:a + 100, g]
            hit = np.flatnonzero(diff != 0)
            latencies.append(int(hit[0])*BIN_MS if len(hit) else None)
        found = [x for x in latencies if x is not None]
        out[name] = {'neurons': len(groups[name]), 'windows': windows,
                     'first_divergence_ms_per_pulse': latencies,
                     'median_first_divergence_ms': float(np.median(found)) if found else None,
                     'pulses_with_divergence_within_1s': len(found)}
    behaviour = {}
    for k, label in enumerate(['turn', 'forward', 'attack_fraction']):
        windows = {}
        for w, (lo, hi) in WINDOWS_MS.items():
            per_pulse = [decoded[(s + lo)//BIN_MS:(s + hi)//BIN_MS, k].mean() - sham_decoded[(s + lo)//BIN_MS:(s + hi)//BIN_MS, k].mean() for s in starts]
            windows[w] = round(float(np.mean(per_pulse)), 5)
        behaviour[label] = windows
    return {'groups': out, 'decoded_open_loop_delta_vs_sham': behaviour}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arms', default='sham,snxx29,random-matched,random-dose-matched')
    p.add_argument('--gain', type=float, default=30.)
    p.add_argument('--calibrate-dose', action='store_true',
                   help='Only calibrate the random-dose-matched gain and write the calibration record')
    p.add_argument('--calibration', default=str(ROOT/'outputs/doom/nociception/dose-calibration-v1.json'))
    p.add_argument('--gain-sweep', default='', help='Comma-separated gains for a single-pulse SNxx29 sweep, e.g. 5,7.5,10,15,20,30,40')
    p.add_argument('--pulses', type=int, default=5)
    p.add_argument('--pulse-ms', type=int, default=200)
    p.add_argument('--interval-ms', type=int, default=1200)
    p.add_argument('--jitter-ms', type=int, default=400)
    p.add_argument('--warmup-ms', type=int, default=2000)
    p.add_argument('--seed', type=int, default=41027, help='Seeds the random population and pulse jitter')
    p.add_argument('--frame', help='RGB image viewed throughout; default uniform gray 64')
    p.add_argument('--out', default=str(ROOT/'outputs/doom/nociception/probe-snxx29-v1'))
    args = p.parse_args()
    arms = args.arms.split(',')
    if not args.calibrate_dose and ('sham' not in arms or not set(arms) <= {'sham', 'snxx29', 'random-matched', 'random-dose-matched'}):
        p.error('Arms must include sham and only sham, snxx29, random-matched, random-dose-matched')
    if args.pulse_ms % BIN_MS or args.interval_ms % BIN_MS or args.warmup_ms % BIN_MS or args.pulse_ms <= 0:
        p.error(f'Durations must be positive multiples of {BIN_MS} ms')

    import pyarrow.feather as feather
    from doom_learning_v6.calibration import calibrated_brain
    from doom.engine import NeuralControls
    from doom.monitor import activity_groups
    from doom.nociception import load_population

    started = time.time()
    brain = calibrated_brain()
    brain.weights_frozen = True
    annotations = feather.read_table(ROOT/'connectome_data/malecns_v1/annotations.feather').to_pandas().set_index('bodyId')
    populations = {s: load_population(s, brain.ids, seed=args.seed, modulation_mask=brain.modulation_mask, annotations=annotations)
                   for s in ['snxx29', 'random-matched']}
    groups = activity_groups(annotations.loc[brain.ids])
    groups = {'random_matched': populations['random-matched']['indices'], **groups}
    manifest = json.loads((ROOT/'outputs/doom/malecns_v1/manifest.json').read_text())
    frame = load_frame(args.frame)
    rng = np.random.default_rng(args.seed)
    starts = onsets(args.pulses, 200, args.interval_ms, args.jitter_ms, rng)
    total_ms = starts[-1] + args.pulse_ms + 1000

    brain.rgb_step(frame, float(args.warmup_ms), learning=False)
    provenance = {'fork_commit': git_commit(), 'kernel': brain.build,
                  'graph_sha256': sha256_file(ROOT/'outputs/doom/malecns_v1/graph.npz'),
                  'configuration': brain.configuration_signature(), 'calibration': brain.calibration,
                  'dataset': 'male-cns', 'dataset_version': 'v1.0'}
    if args.calibrate_dose:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)/'equilibrated.npz'
            brain.checkpoint(state)
            controls = NeuralControls(manifest['readouts'], mode='bci')
            target, chosen, search = calibrate_dose(brain, state, frame, groups, controls, populations['snxx29']['indices'],
                                                    populations['random-matched']['indices'], args.gain, args.pulse_ms)
        record = {'schema': 1, 'purpose': 'Gain for the random-dose-matched control: equal population spike rate to SNxx29, not equal drive.',
                  'seed': args.seed, 'pulse_ms': float(args.pulse_ms), 'decay_ms': 0., 'warmup_ms': args.warmup_ms,
                  'frame_sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                  'snxx29_gain_mv': args.gain, 'snxx29_rate_hz': round(target, 4),
                  'random_dose_matched_gain_mv': chosen['gain_mv'], 'random_rate_hz': chosen['random_rate_hz'],
                  'relative_rate_error': round(abs(chosen['random_rate_hz'] - target)/target, 4) if target else None,
                  'search': search, 'random_population_body_ids': [r['body_id'] for r in populations['random-matched']['report']['neurons']],
                  'limits': 'Matched for one pulse at full damage from one equilibrated state on a fixed frame. In-game dose still varies with network state and hit size, and spikes scale nonlinearly with drive.',
                  'provenance': provenance, 'wall_seconds': round(time.time() - started, 1)}
        path = Path(args.calibration)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2)+'\n')
        print(json.dumps({k: record[k] for k in ['snxx29_gain_mv', 'snxx29_rate_hz', 'random_dose_matched_gain_mv', 'random_rate_hz', 'relative_rate_error']}))
        print(path)
        return
    gains = {'snxx29': args.gain, 'random-matched': args.gain}
    calibration = None
    if 'random-dose-matched' in arms:
        from doom.nociception import load_dose_calibration
        calibration = load_dose_calibration(args.calibration, seed=args.seed, pulse_ms=args.pulse_ms, decay_ms=0.)
        if float(calibration['snxx29_gain_mv']) != args.gain:
            p.error('Dose calibration was made for a different SNxx29 gain')
        gains['random-dose-matched'] = calibration['random_dose_matched_gain_mv']
        populations['random-dose-matched'] = populations['random-matched']
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    series = {}
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)/'equilibrated.npz'
        brain.checkpoint(state)
        results = {}
        for arm in arms:
            brain.restore(state)
            controls = NeuralControls(manifest['readouts'], mode='bci')
            indices = None if arm == 'sham' else populations[arm]['indices']
            t0 = time.time()
            spikes, decoded = run_arm(brain, frame, groups, controls, indices=indices, gain=gains.get(arm, 0.),
                                      starts=starts, pulse_ms=args.pulse_ms, total_ms=total_ms)
            series[arm] = (spikes, decoded)
            print(json.dumps({'arm': arm, 'neural_ms': total_ms, 'wall_s': round(time.time() - t0, 1)}), flush=True)
        for arm in arms:
            if arm != 'sham':
                results[arm] = summarize(*series[arm], *series['sham'], groups, starts)
        dose = {}
        for arm, key in [('snxx29', 'SNxx29'), ('random-matched', 'random_matched'), ('random-dose-matched', 'random_matched')]:
            if arm in series:
                col = list(groups).index(key)
                during = sum(series[arm][0][s//BIN_MS:(s + args.pulse_ms)//BIN_MS, col].sum() for s in starts)
                dose[arm] = {'gain_mv': gains[arm], 'stimulated_population_spikes_during_pulses': int(during),
                             'rate_hz': round(during/len(groups[key])/(len(starts)*args.pulse_ms/1000), 3)}
        sweep = []
        for gain in [float(x) for x in args.gain_sweep.split(',') if x.strip()]:
            brain.restore(state)
            controls = NeuralControls(manifest['readouts'], mode='bci')
            spikes, _ = run_arm(brain, frame, groups, controls, indices=populations['snxx29']['indices'], gain=gain,
                                starts=[100], pulse_ms=args.pulse_ms, total_ms=100 + args.pulse_ms + 200)
            during = spikes[10:10 + args.pulse_ms//BIN_MS]
            names = list(groups)
            sweep.append({'gain_mv': gain, **{f'{k}_rate_hz': round(float(during[:, names.index(k)].sum()/max(1, len(groups[k]))/(args.pulse_ms/1000)), 3)
                                              for k in ['SNxx29', 'AN09B018', 'AN05B004', 'ascending_neuron', 'DAN', 'descending_neuron']}})
            print(json.dumps(sweep[-1]), flush=True)
    np.savez_compressed(out/'series.npz', groups=np.array(list(groups)), bin_ms=BIN_MS, starts_ms=np.array(starts),
                        **{f'{arm}_spikes': s for arm, (s, _) in series.items()},
                        **{f'{arm}_decoded_turn_forward_attack': d for arm, (_, d) in series.items()})
    report = {'schema': 1, 'experiment': 'nociception-open-loop-probe', 'milestone': 3,
              'claim': 'Model propagation under an artificial drive; not pain, not validated physiology.',
              'deterministic': True, 'weights_frozen': True, 'game_running': False,
              'parameters': {**{k: v for k, v in vars(args).items() if k != 'out'}, 'bin_ms': BIN_MS, 'pulse_onsets_ms': starts,
                             'windows_ms': WINDOWS_MS, 'frame_sha256': hashlib.sha256(frame.tobytes()).hexdigest()},
              'provenance': provenance, 'dose_calibration': calibration,
              'populations': {k: v['report'] for k, v in populations.items()},
              'dose_check': dose, 'gain_sweep': sweep, 'results': results,
              'group_definitions': {k: len(v) for k, v in groups.items()},
              'wall_seconds': round(time.time() - started, 1)}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(out/'report.json')


if __name__ == '__main__':
    main()
