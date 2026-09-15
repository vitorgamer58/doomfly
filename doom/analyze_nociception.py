"""Milestone 4: behavior and recorded activity around damage, compared across damage inputs.

Reads only the audit written by doom.server (audit.jsonl*, hourly archive
and lives.jsonl). Every damage event is a within-run comparison of the
window after the hit against the second before it. Conditions are then
compared by bootstrap confidence intervals of those per-event changes.

Mandatory caveat: ViZDoom tints the screen when the player is hit, so every
condition, including "none", receives a visual damage signal. The "none" and
"random-matched" conditions exist to separate that from nociceptor topology.
A difference here is a model response, not evidence of pain or learning.
"""
import argparse
import gzip
import json
from pathlib import Path
import numpy as np

WINDOWS_MS = {'post_0_200': (0, 200), 'post_200_1000': (200, 1000)}
PRE_MS = (-1000, 0)
REFERENCE = 'none'
BOOTSTRAP = 2000
MONITOR_KEYS = ['stimulated', 'SNxx29', 'AN09B018', 'AN05B004', 'ascending_neuron', 'DAN', 'PPL101', 'MBON', 'descending_neuron',
                'DNp20_L', 'DNp20_R', 'DNpe017']


def read_events(directory):
    directory = Path(directory)
    rows = {}
    paths = sorted(directory.glob('archive/*.jsonl.gz')) + sorted(directory.glob('audit.jsonl*'))
    for path in paths:
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    rows[(e['run_id'], e['tick'])] = e
    return sorted(rows.values(), key=lambda e: (e['recorded_at_ms'], e['run_id'], e['tick']))


def read_lives(directory):
    path = Path(directory)/'lives.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def features(e):
    applied = e['applied']
    rates = {}
    for r in e.get('readouts', []):
        if r['type'] in ('DNp20', 'DNpe017'):
            rates[(r['type'], r.get('side'))] = rates.get((r['type'], r.get('side')), 0.) + r['rate_hz']
    out = {'abs_turn': abs(applied['turn']), 'turn': applied['turn'], 'forward': applied['forward'],
           'attack': float(applied['attack']),
           'DNp20_R_minus_L_hz': rates.get(('DNp20', 'R'), 0.) - rates.get(('DNp20', 'L'), 0.),
           'DNpe017_hz': sum(v for (t, _), v in rates.items() if t == 'DNpe017')}
    for k in MONITOR_KEYS:
        if k in e.get('monitor', {}):
            out[f'spikes_per_tic_{k}'] = e['monitor'][k]
    return out


def damage_windows(events):
    """Per nonfatal damage event: post-minus-pre change of every feature, per window."""
    results = []
    by_run = {}
    for e in events:
        by_run.setdefault(e['run_id'], []).append(e)
    for run in by_run.values():
        times = np.array([e['neural_ms'] for e in run])
        for i in range(1, len(run)):
            a, b = run[i - 1], run[i]
            if a['episode'] != b['episode'] or b['game'].get('finished'):
                continue
            if b['game']['health'] >= a['game']['health']:
                continue
            t0 = b['neural_ms']
            def window(lo, hi):
                ix = np.flatnonzero((times > t0 + lo) & (times <= t0 + hi))
                return [run[j] for j in ix]
            pre = window(*PRE_MS)
            if not pre or any(e['episode'] != b['episode'] for e in pre):
                continue
            record = {'neural_ms': t0, 'damage': a['game']['health'] - b['game']['health'], 'deltas': {},
                      'crosses_respawn': False, 'further_damage_within_1s': False}
            later = window(0, 1000)
            record['crosses_respawn'] = any(e['episode'] != b['episode'] or e['game'].get('finished') for e in later)
            record['further_damage_within_1s'] = any(
                later[k]['episode'] == b['episode'] and later[k]['game']['health'] < (later[k-1] if k else b)['game']['health']
                for k in range(len(later)))
            base = features_mean(pre)
            for label, (lo, hi) in WINDOWS_MS.items():
                post = [e for e in window(lo, hi) if e['episode'] == b['episode']]
                if post:
                    m = features_mean(post)
                    record['deltas'][label] = {k: m[k] - base[k] for k in m if k in base}
            results.append(record)
    return results


def features_mean(events):
    rows = [features(e) for e in events]
    keys = set.intersection(*(set(r) for r in rows))
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


def bootstrap_mean(values, rng):
    values = np.asarray(values, dtype=np.float64)
    if len(values) < 2:
        return {'n': len(values), 'mean': float(values.mean()) if len(values) else None, 'ci95': None}
    samples = rng.choice(values, size=(BOOTSTRAP, len(values)), replace=True).mean(axis=1)
    return {'n': len(values), 'mean': float(values.mean()), 'ci95': [float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))]}


def bootstrap_difference(a, b, rng):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if len(a) < 2 or len(b) < 2:
        return None
    diff = rng.choice(a, size=(BOOTSTRAP, len(a))).mean(axis=1) - rng.choice(b, size=(BOOTSTRAP, len(b))).mean(axis=1)
    return {'difference': float(a.mean() - b.mean()), 'ci95': [float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))]}


def condition_summary(windows, rng):
    clean = [w for w in windows if not w['crosses_respawn']]
    summary = {'damage_events': len(windows), 'analyzed_events': len(clean),
               'excluded_crossing_respawn': len(windows) - len(clean),
               'fraction_with_further_damage_within_1s': round(float(np.mean([w['further_damage_within_1s'] for w in clean])), 4) if clean else None,
               'windows': {}}
    for label in WINDOWS_MS:
        rows = [w['deltas'][label] for w in clean if label in w['deltas']]
        keys = sorted(set.intersection(*(set(r) for r in rows))) if rows else []
        summary['windows'][label] = {k: bootstrap_mean([r[k] for r in rows], rng) for k in keys}
    return summary, clean


def lives_summary(lives):
    complete = [l for l in lives if not l['censored']]
    if not complete:
        return {'lives': len(lives), 'complete_lives': 0}
    survival = np.array([l['survival_seconds'] for l in complete])
    half = len(complete)//2
    return {'lives': len(lives), 'complete_lives': len(complete), 'deaths': sum(l['died'] for l in complete),
            'median_survival_seconds': float(np.median(survival)),
            'mean_damage_per_minute': float(np.mean([l['damage_per_minute'] for l in complete])),
            'mean_kills_per_life': float(np.mean([l['kills'] for l in complete])),
            'median_survival_first_half': float(np.median(survival[:half])) if half else None,
            'median_survival_second_half': float(np.median(survival[half:])) if half else None,
            'note': 'Frozen-weight runs: survival differences across halves are not learning evidence.'}


def analyze(runs, seed=0):
    rng = np.random.default_rng(seed)
    report = {'schema': 1, 'milestone': 4, 'windows_ms': {'pre': PRE_MS, **WINDOWS_MS}, 'bootstrap_resamples': BOOTSTRAP,
              'caveat': __doc__.split('Mandatory caveat: ')[1].strip(), 'conditions': {}, 'comparisons_vs_none': {}}
    clean = {}
    for label, directory in runs.items():
        events = read_events(directory)
        modes = {e.get('learning', {}).get('damage_input') for e in events}
        summary, clean[label] = condition_summary(damage_windows(events), rng)
        report['conditions'][label] = {'directory': str(directory), 'damage_inputs_in_audit': sorted(m for m in modes if m),
                                       'events': len(events), **summary, 'lives': lives_summary(read_lives(directory))}
    if REFERENCE in clean:
        for label in clean:
            if label == REFERENCE:
                continue
            report['comparisons_vs_none'][label] = {}
            for window in WINDOWS_MS:
                a = [w['deltas'][window] for w in clean[label] if window in w['deltas']]
                b = [w['deltas'][window] for w in clean[REFERENCE] if window in w['deltas']]
                keys = sorted(set.intersection(*(set(r) for r in a + b))) if a and b else []
                report['comparisons_vs_none'][label][window] = {k: bootstrap_difference([r[k] for r in a], [r[k] for r in b], rng) for k in keys}
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--run', action='append', required=True, help='label=audit_directory, e.g. snxx29=outputs/doom/nociception/run-snxx29')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--out', default='outputs/doom/nociception/analysis-v1.json')
    args = p.parse_args()
    runs = dict(item.split('=', 1) for item in args.run)
    report = analyze(runs, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+'\n')
    for label, c in report['conditions'].items():
        print(f"{label}: {c['analyzed_events']} damage events, lives={c['lives'].get('complete_lives')}")
    print(out)


if __name__ == '__main__':
    main()
