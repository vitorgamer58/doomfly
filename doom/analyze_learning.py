"""Milestone 6/7: descriptive curves over simulation_age, per arm.

Reads only doom.server's own logs (lives.jsonl, weights.jsonl). Bins lives by
their start simulation_age into fixed-width windows and reports median
survival, mean damage/min and mean kills per bin, plus KC->MBON11 weight
statistics over the same axis when the arm ran with --learning. There is no
significance test here: a trend across bins within one arm, compared across
arms, is what task_atualizado.md section 24 calls a learning curve, not
evidence by itself. Any claim of learning still needs the arm comparisons in
section 25 (A vs B vs C vs D vs E vs F).
"""
import argparse
import json
from pathlib import Path
import numpy as np

BIN_SECONDS = 300.


def read_jsonl(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def bin_lives(lives, bin_seconds):
    complete = [l for l in lives if not l['censored']]
    if not complete:
        return []
    bin_ms = bin_seconds*1000
    max_age = max(l['end_simulation_age_ms'] for l in complete)
    bins = []
    for lo in np.arange(0., max_age + bin_ms, bin_ms):
        rows = [l for l in complete if lo <= l['start_simulation_age_ms'] < lo + bin_ms]
        if not rows:
            continue
        survival = np.array([l['survival_seconds'] for l in rows])
        bins.append({'bin_start_simulation_age_ms': round(float(lo), 1), 'lives': len(rows),
            'median_survival_seconds': float(np.median(survival)),
            'mean_damage_per_minute': float(np.mean([l['damage_per_minute'] for l in rows])),
            'mean_kills_per_life': float(np.mean([l['kills'] for l in rows])),
            'deaths': int(sum(l['died'] for l in rows))})
    return bins


def bin_weights(weights, bin_seconds):
    if not weights:
        return []
    bin_ms = bin_seconds*1000
    max_age = max(w['simulation_age_ms'] for w in weights)
    bins = []
    for lo in np.arange(0., max_age + bin_ms, bin_ms):
        rows = [w for w in weights if lo <= w['simulation_age_ms'] < lo + bin_ms]
        if not rows:
            continue
        last = rows[-1]
        bins.append({'bin_start_simulation_age_ms': round(float(lo), 1), 'samples': len(rows),
            'mean_efficacy': last['mean_efficacy'], 'minimum_efficacy': last['minimum_efficacy'],
            'changed_edges': last['changed_edges'], 'plastic_edges': last['plastic_edges']})
    return bins


def analyze_learning(runs, bin_seconds=BIN_SECONDS, max_simulation_age_ms=None):
    """max_simulation_age_ms: trim every arm to the same absolute neural time before binning, so an
    arm that happened to accumulate extra time across interrupt/resume cycles doesn't show bins the
    other arms don't have. See analyze_nociception.analyze for the same trim on the peri-damage side.
    """
    report = {'schema': 1, 'milestone': 6, 'bin_seconds': bin_seconds, 'max_simulation_age_ms': max_simulation_age_ms,
        'caveat': __doc__.split('There is no')[1].strip(), 'arms': {}}
    for label, directory in runs.items():
        directory = Path(directory)
        lives = read_jsonl(directory/'lives.jsonl')
        weights = read_jsonl(directory/'weights.jsonl')
        if max_simulation_age_ms is not None:
            lives = [l for l in lives if l['end_simulation_age_ms'] <= max_simulation_age_ms]
            weights = [w for w in weights if w['simulation_age_ms'] <= max_simulation_age_ms]
        report['arms'][label] = {'lives_by_simulation_age': bin_lives(lives, bin_seconds),
            'weights_by_simulation_age': bin_weights(weights, bin_seconds),
            'total_lives': len(lives), 'learning_enabled': bool(weights)}
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--run', action='append', required=True, help='label=audit_directory')
    p.add_argument('--bin-seconds', type=float, default=BIN_SECONDS)
    p.add_argument('--max-simulation-age-ms', type=float, help='Trim every run to this much total neural time before analysis')
    p.add_argument('--out', default='outputs/doom/nociception/learning-curves.json')
    args = p.parse_args()
    runs = dict(item.split('=', 1) for item in args.run)
    report = analyze_learning(runs, args.bin_seconds, max_simulation_age_ms=args.max_simulation_age_ms)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2)+'\n')
    for label, a in report['arms'].items():
        print(f"{label}: {a['total_lives']} lives, {len(a['lives_by_simulation_age'])} bins, learning={a['learning_enabled']}")
    print(out)


if __name__ == '__main__':
    main()
