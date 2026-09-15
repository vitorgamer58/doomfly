"""Simulated nociception: Doom health loss -> identified MaleCNS sensory neurons.

Doom hit points have no biological equivalent in millivolts. The transducer
below is an explicit engineering conversion, not measured nociceptor
physiology, and nothing here claims the simulation feels pain.

Population identity comes only from MaleCNS v1.0 (male-cns:v1.0) annotations.
SNxx29 is selected by exact type, with side from rootSide (somaSide is empty
for these nerve-entering sensory cells). The ppk+/Gr28b.d+ heat-nociceptor
interpretation is inferred from MANC-era literature: the v1.0 annotations
carry no receptorType for these cells and the MaleCNS paper does not describe
them. The random control draws leg sensory neurons matched for side, model
transmitter and outgoing synapse count, so the stimulated population differs
in identity and topology, not in size, sign, dose or output degree.
"""
import argparse
import json
import math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'connectome_data/malecns_v1'
DATASET = {'dataset': 'male-cns', 'dataset_version': 'v1.0'}
SOURCES = ('snxx29', 'random-matched')
RANDOM_SOURCES = ('random-matched', 'random-dose-matched')
DOSE_CALIBRATION = ROOT/'outputs/doom/nociception/dose-calibration-v1.json'
SNXX29 = 'SNxx29'
PER_SIDE = 10
MATCH_NEIGHBOURS = 3
MATCH_TOLERANCE = .10
MATCH_ATTEMPTS = 1000
DECAY_BIN_STEPS = 100
MODULATORY = ['dopamine', 'octopamine', 'serotonin']
IDENTITY_EVIDENCE = ('ppk+/Gr28b.d+ heat-nociceptive leg sensory identity is inferred from MANC-era '
    'annotation literature. MaleCNS v1.0 has no receptorType for these cells and the MaleCNS paper '
    '(Berg et al.) does not describe SNxx29 or nociception.')


def _types(annotations):
    return annotations['type'].fillna('').astype(str)


def _sides(annotations):
    return annotations['rootSide'].fillna('').astype(str).to_numpy()


def snxx29_indices(annotations, transmitter):
    """Exact SNxx29 cells; composite types such as 'SNxx27,SNxx29' are excluded."""
    ix = np.flatnonzero(_types(annotations).eq(SNXX29).to_numpy()).astype(np.int32)
    sides = _sides(annotations)[ix]
    if len(ix) != 2*PER_SIDE or np.count_nonzero(sides == 'L') != PER_SIDE or np.count_nonzero(sides == 'R') != PER_SIDE:
        raise ValueError('Expected 10 left and 10 right SNxx29 cells (rootSide) in MaleCNS v1.0.')
    if np.any(np.asarray(transmitter)[ix] != 'acetylcholine'):
        raise ValueError('Every SNxx29 cell must carry the acetylcholine model transmitter.')
    return ix


def matched_random_indices(annotations, transmitter, outgoing, reference, seed, modulation_mask=None):
    """Leg sensory neurons matched one-to-one to the reference for side and output degree.

    Returns (indices, attempts). In MaleCNS v1.0 the two strongest left SNxx29
    cells exceed every left leg sensory candidate, so even nearest-neighbour
    matching undershoots the total. Whole draws are therefore repeated from the
    same seeded generator until total outgoing synapses fall within tolerance.
    """
    if seed is None:
        raise ValueError('The random-matched control requires an explicit seed.')
    rng = np.random.default_rng(seed)
    transmitter = np.asarray(transmitter)
    outgoing = np.asarray(outgoing, dtype=np.float64)
    reference = np.asarray(reference)
    sides = _sides(annotations)
    pool = (annotations['superclass'].eq('vnc_sensory').to_numpy()
        & annotations['subclass'].eq('leg').to_numpy()
        & (transmitter == 'acetylcholine')
        & ~_types(annotations).str.contains(SNXX29, regex=False).to_numpy())
    if modulation_mask is not None:
        pool &= np.asarray(modulation_mask) == 0
    for attempt in range(1, MATCH_ATTEMPTS + 1):
        chosen = []
        # Random matching order so the closest candidates are not reserved for one part of the degree range.
        for r in rng.permutation(reference):
            candidates = np.flatnonzero(pool & (sides == sides[r]))
            candidates = candidates[~np.isin(candidates, chosen)]
            if len(candidates) < MATCH_NEIGHBOURS:
                raise ValueError('Too few leg sensory candidates for a matched random control.')
            distance = np.abs(outgoing[candidates] - outgoing[r])
            nearest = candidates[np.argsort(distance, kind='stable')[:MATCH_NEIGHBOURS]]
            chosen.append(int(rng.choice(nearest)))
        chosen = np.sort(np.asarray(chosen, dtype=np.int32))
        if abs(outgoing[chosen].sum()/outgoing[reference].sum() - 1) <= MATCH_TOLERANCE:
            return chosen, attempt
    raise ValueError(f'No matched random control within {MATCH_TOLERANCE:.0%} outgoing synapses after {MATCH_ATTEMPTS} draws.')


def select_population(source, annotations, transmitter, outgoing, *, seed=None, modulation_mask=None, predictions=None):
    """Return stimulated node indices plus a per-neuron provenance report.

    annotations: row i describes node i (index bodyId); transmitter: model
    transmitter per node; outgoing: outgoing synapse count per node;
    predictions: optional neurotransmitter prediction table indexed by body.
    """
    reference = snxx29_indices(annotations, transmitter)
    attempts = None
    if source == 'snxx29':
        indices = reference
        rule = 'Exact type == "SNxx29"; side from rootSide; 10 L + 10 R; acetylcholine model transmitter.'
        seed = None
    elif source in RANDOM_SOURCES:
        indices, attempts = matched_random_indices(annotations, transmitter, outgoing, reference, seed, modulation_mask)
        rule = (f'For each SNxx29 cell, one draw without replacement from the {MATCH_NEIGHBOURS} nearest '
            'same-side leg sensory neurons (superclass vnc_sensory, subclass leg, acetylcholine, non-modulatory, '
            f'not SNxx29) by outgoing synapse count; whole draws repeated from the seeded generator until total '
            f'outgoing synapses are within {MATCH_TOLERANCE:.0%}.')
        if source == 'random-dose-matched':
            rule += (' Same cells as random-matched for this seed; the drive gain is calibrated separately so the '
                'population spike rate matches SNxx29 (see the dose calibration record).')
    else:
        raise ValueError(f'Unknown nociceptive population: {source}')
    transmitter = np.asarray(transmitter)
    outgoing = np.asarray(outgoing)
    sides = _sides(annotations)
    rows = []
    def text(value):
        return None if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)
    for i in indices:
        a = annotations.iloc[i]
        body = int(annotations.index[i])
        row = {'index': int(i), 'body_id': str(body), 'type': text(a['type']), 'class': text(a['class']),
            'superclass': text(a['superclass']), 'subclass': text(a['subclass']), 'side': str(sides[i]),
            'entry_nerve': text(a['entryNerve']) if 'entryNerve' in a else None,
            'model_neurotransmitter': str(transmitter[i]), 'outgoing_synapses': int(outgoing[i]), **DATASET}
        if predictions is not None and body in predictions.index:
            p = predictions.loc[body]
            row.update({'predicted_nt': str(p['predicted_nt']),
                'predicted_nt_confidence': float(p['predicted_nt_confidence']),
                'celltype_predicted_nt': str(p['celltype_predicted_nt']),
                'celltype_predicted_nt_confidence': float(p['celltype_predicted_nt_confidence'])})
        rows.append(row)
    report = {'source': source, 'selection_rule': rule, 'seed': seed, 'count': len(indices),
        'sides': {s: int(np.count_nonzero(sides[indices] == s)) for s in ['L', 'R']},
        'outgoing_synapses_total': int(outgoing[indices].sum()),
        'reference_snxx29_outgoing_synapses_total': int(outgoing[reference].sum()),
        'outgoing_ratio_to_snxx29': round(float(outgoing[indices].sum()/outgoing[reference].sum()), 4),
        'match_attempts': attempts,
        'identity_evidence': IDENTITY_EVIDENCE if source == 'snxx29' else 'Control: identity deliberately not nociceptive-specific.',
        'neurons': rows, **DATASET}
    return {'source': source, 'indices': indices, 'report': report}


def load_population(source, ids, *, seed=None, modulation_mask=None, annotations=None):
    """Select a population for a graph whose node order is given by body ``ids``."""
    import pyarrow.feather as feather
    ids = np.asarray(ids, dtype=np.int64)
    if not np.array_equal(np.load(DATA/'normalized/neuron_ids.npy').astype(np.int64), ids):
        raise ValueError('Graph node order differs from the normalized MaleCNS import.')
    if annotations is None:
        annotations = feather.read_table(DATA/'annotations.feather').to_pandas().set_index('bodyId')
    a = annotations.loc[ids]
    nodes = feather.read_table(DATA/'normalized/neurons.feather').to_pandas().set_index('source_id').loc[ids]
    transmitter = nodes['neurotransmitter'].fillna('').astype(str).to_numpy()
    if modulation_mask is None:
        modulation_mask = nodes['neurotransmitter'].isin(MODULATORY).to_numpy(dtype=np.uint8)
    outgoing = np.load(DATA/'normalized/outgoing_synapse_counts.npy')
    predictions = feather.read_table(DATA/'neurotransmitters.feather', columns=['body', 'predicted_nt',
        'predicted_nt_confidence', 'celltype_predicted_nt', 'celltype_predicted_nt_confidence']).to_pandas().set_index('body')
    return select_population(source, a, transmitter, outgoing, seed=seed,
        modulation_mask=modulation_mask, predictions=predictions)


def load_dose_calibration(path, *, seed, pulse_ms, decay_ms):
    """Validated gain for the random-dose-matched control.

    The SNxx29 feedback loop (AN05B004 inhibits SNxx29) keeps SNxx29 far below
    a same-drive random population, so equal amplitude is not equal spike dose.
    The calibration matches single-pulse population rates on one equilibrated
    state and frame; in-game dose still depends on state and hit size.
    """
    import hashlib
    path = Path(path)
    raw = path.read_bytes()
    c = json.loads(raw)
    required = {'schema', 'seed', 'pulse_ms', 'decay_ms', 'snxx29_gain_mv', 'snxx29_rate_hz',
                'random_dose_matched_gain_mv', 'random_rate_hz'}
    if c.get('schema') != 1 or not required <= set(c):
        raise ValueError('Invalid nociception dose calibration record')
    if c['seed'] != seed or float(c['pulse_ms']) != float(pulse_ms) or float(c['decay_ms']) != float(decay_ms):
        raise ValueError('Dose calibration was made for a different seed, pulse duration or decay')
    gain = float(c['random_dose_matched_gain_mv'])
    if not math.isfinite(gain) or gain <= 0:
        raise ValueError('Invalid calibrated gain')
    return {**{k: c[k] for k in sorted(required)}, 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


class NociceptiveTransducer:
    """Artificial health-loss transducer driving one population bilaterally.

    damage_delta = max(previous_health - max(current_health, 0), 0)
    damage_normalized = clip(damage_delta / damage_reference, 0, 1)
    drive_mv = gain * damage_normalized

    Drive is a mV-equivalent steady-state depolarization added to every
    selected cell for pulse_ms, optionally decaying with time constant
    decay_ms (0 = constant). A new hit restarts the pulse at the larger of the
    remaining and the new drive. Fatal damage also drives the population, and a
    pulse is never cancelled by an arena reset: the brain experiences intense
    nociception followed by the abrupt new-arena image. None of these values
    is physiologically calibrated.
    """
    INTEGER_STATE = ['until', 'onset', 'events', 'terminal_events', 'delivered_steps', 'last_steps', 'spans_respawn']
    FLOAT_STATE = ['peak', 'damage_total', 'delivered_dose']

    def __init__(self, population, *, gain, pulse_ms=200., decay_ms=0., damage_reference=20.,
                 left_right_mode='bilateral', dt_ms=.1, calibration=None):
        values = {'gain': gain, 'pulse_ms': pulse_ms, 'decay_ms': decay_ms, 'damage_reference': damage_reference}
        if not all(math.isfinite(float(v)) for v in values.values()):
            raise ValueError('Finite nociception parameters required')
        if gain <= 0 or pulse_ms <= 0 or decay_ms < 0 or damage_reference <= 0:
            raise ValueError('Nociception requires gain > 0, pulse_ms > 0, decay_ms >= 0 and damage_reference > 0')
        if left_right_mode != 'bilateral':
            raise ValueError('Only bilateral nociception is implemented; lateralized input is a separate experiment')
        indices = np.asarray(population['indices'], dtype=np.int32)
        if indices.ndim != 1 or not len(indices) or len(np.unique(indices)) != len(indices):
            raise ValueError('A nonempty set of unique neuron indices is required')
        if (population['source'] == 'random-dose-matched') != (calibration is not None):
            raise ValueError('A dose calibration is required exactly for the random-dose-matched control')
        self.source = population['source']
        self.report = population['report']
        self.calibration = calibration
        self.indices = indices
        self.gain = float(gain)
        self.pulse_ms = float(pulse_ms)
        self.decay_ms = float(decay_ms)
        self.damage_reference = float(damage_reference)
        self.left_right_mode = left_right_mode
        self.dt_ms = float(dt_ms)
        self.pulse_steps = round(self.pulse_ms/self.dt_ms)
        if self.pulse_steps < 1:
            raise ValueError('Pulse shorter than one integration step')
        for k in self.INTEGER_STATE:
            setattr(self, k, 0)
        for k in self.FLOAT_STATE:
            setattr(self, k, 0.)
        self.last_drive = 0.

    def parameters(self):
        out = {'source': self.source, 'gain_mv': self.gain, 'pulse_ms': self.pulse_ms, 'decay_ms': self.decay_ms,
            'damage_reference_hp': self.damage_reference, 'left_right_mode': self.left_right_mode,
            'seed': self.report['seed'], 'body_ids': [r['body_id'] for r in self.report['neurons']],
            'transducer': 'drive_mv = gain * clip(max(previous_health - max(current_health, 0), 0) / damage_reference, 0, 1); '
                'engineering conversion, not physiology'}
        if self.calibration is not None:
            out['dose_calibration'] = self.calibration
        return out

    def amplitude(self, cursor):
        if cursor >= self.until or cursor < self.onset or self.peak <= 0:
            return 0.
        if not self.decay_ms:
            return self.peak
        return self.peak*math.exp(-(cursor - self.onset)*self.dt_ms/self.decay_ms)

    def boundaries(self, cursor, steps):
        """Integration-step offsets inside [0, steps] where the drive changes."""
        remaining = self.until - cursor
        if remaining <= 0:
            return []
        cuts = [remaining] if remaining < steps else []
        if self.decay_ms:
            cuts += list(range(DECAY_BIN_STEPS, min(remaining, steps), DECAY_BIN_STEPS))
        return cuts

    def begin_tic(self):
        self.last_steps = 0
        self.last_drive = 0.

    def deliver(self, steps, amplitude):
        if not self.last_steps:
            self.last_drive = float(amplitude)
        self.last_steps += steps
        self.delivered_steps += steps
        self.delivered_dose += amplitude*steps*self.dt_ms

    def observe(self, before, after, cursor):
        damage = max(0., float(before['health']) - max(0., float(after['health'])))
        if not damage:
            return 0.
        drive = self.gain*min(1., damage/self.damage_reference)
        self.peak = max(self.amplitude(cursor), drive)
        self.onset = cursor
        self.until = cursor + self.pulse_steps
        self.events += 1
        self.terminal_events += int(bool(after.get('finished')))
        self.damage_total += damage
        return drive

    def new_round(self, cursor):
        # Deliberately not cancelled: death is not a special neural event.
        self.spans_respawn += int(self.until > cursor)

    def state(self):
        return {k: getattr(self, k) for k in [*self.INTEGER_STATE, *self.FLOAT_STATE]}

    def restore(self, state):
        if not isinstance(state, dict) or set(state) != set(self.state()):
            raise ValueError('Invalid nociception checkpoint')
        for k in self.INTEGER_STATE:
            if type(state[k]) is not int or state[k] < 0:
                raise ValueError('Invalid nociception checkpoint')
        for k in self.FLOAT_STATE:
            if type(state[k]) not in (int, float) or not math.isfinite(state[k]) or state[k] < 0:
                raise ValueError('Invalid nociception checkpoint')
        for k, v in state.items():
            setattr(self, k, float(v) if k in self.FLOAT_STATE else v)

    def telemetry(self):
        return {'source': self.source, 'neurons': len(self.indices), 'gain_mv': self.gain,
            'pulse_ms': self.pulse_ms, 'decay_ms': self.decay_ms, 'damage_reference_hp': self.damage_reference,
            'left_right_mode': self.left_right_mode, 'events': self.events, 'terminal_events': self.terminal_events,
            'damage_total_hp': self.damage_total, 'delivered_ms': round(self.delivered_steps*self.dt_ms, 3),
            'delivered_dose_mv_ms': round(self.delivered_dose, 3), 'stimulus_active': self.last_steps > 0,
            'stimulus_steps_last_tic': self.last_steps, 'drive_mv_last_tic': round(self.last_drive, 4),
            'pulses_spanning_respawn': self.spans_respawn, 'physiologically_calibrated': False}


def main():
    p = argparse.ArgumentParser(description='Export nociceptive and matched-control populations with provenance.')
    p.add_argument('command', choices=['export'])
    p.add_argument('--seed', type=int, default=41027, help='Seed for the matched random control')
    p.add_argument('--out', default=str(ROOT/'outputs/doom/nociception/populations-malecns_v1.json'))
    args = p.parse_args()
    with np.load(ROOT/'outputs/doom/malecns_v1/graph.npz') as g:
        ids = g['ids']
    record = {'schema': 1, **DATASET, 'neurons_in_graph': len(ids),
        'populations': {source: load_population(source, ids, seed=args.seed)['report'] for source in SOURCES}}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2)+'\n')
    for source, r in record['populations'].items():
        print(f"{source}: {r['count']} cells {r['sides']} outgoing={r['outgoing_synapses_total']} "
              f"(SNxx29 {r['reference_snxx29_outgoing_synapses_total']})")
    print(out)


if __name__ == '__main__':
    main()
