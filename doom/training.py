"""Live adapter for the explicitly unvalidated v6 memory hypothesis.

Only images enter the visual model. Health loss reaches the network through one
explicit damage input:

- ppl101: nonfatal health loss schedules next-step PPL101 current (upstream);
  terminal damage and interrupted pulses are recorded, not paired with a fresh
  round's unrelated image.
- none: no neural damage signal; only the game image changes.
- snxx29 / snch01 and their matched-random controls: an artificial transducer
  drives an identified sensory population (doom/nociception.py); PPL101 is not
  stimulated by damage.

The fixed decoder receives only actual neural spike counts. No game state
selects buttons or directly sets weights, and no damage reward exists.
"""
import hashlib
import numpy as np
from doom.nociception import SOURCES as NOCICEPTIVE_INPUTS
DAMAGE_INPUTS = ('ppl101', 'none', *NOCICEPTIVE_INPUTS)


class DamageTraining:
    def __init__(self, brain, enabled=True, *, damage_input='ppl101', nociception=None):
        if damage_input not in DAMAGE_INPUTS:
            raise ValueError(f'Unknown damage input: {damage_input}')
        if (nociception is not None) != (damage_input in NOCICEPTIVE_INPUTS):
            raise ValueError('A nociceptive transducer is required exactly for the sensory damage inputs')
        if nociception is not None and nociception.source != damage_input:
            raise ValueError('Transducer population does not match the damage input')
        self.brain = brain
        self.enabled = bool(enabled)
        self.brain.weights_frozen = not self.enabled
        self.damage_input = damage_input
        self.ppl101_pulse = damage_input == 'ppl101'
        self.nociception = nociception
        self.until = 0
        self.events = 0
        self.delivered_steps = 0
        self.last_steps = 0
        self.terminal_events = 0
        self.cancelled_steps = 0

    def state(self):
        state = {k: getattr(self, k) for k in ['until', 'events', 'delivered_steps',
            'last_steps', 'terminal_events', 'cancelled_steps']}
        if self.nociception is not None:
            state['nociception'] = self.nociception.state()
        return state

    def restore(self, state):
        if set(state) != set(self.state()):
            raise ValueError('Invalid reinforcement checkpoint')
        base = {k: v for k, v in state.items() if k != 'nociception'}
        if any(type(v) is not int or v < 0 for v in base.values()):
            raise ValueError('Invalid reinforcement checkpoint')
        if self.nociception is not None:
            self.nociception.restore(state['nociception'])
        for k, v in base.items():
            setattr(self, k, v)

    def new_round(self):
        self.cancelled_steps += max(0, self.until - self.brain.cursor)
        self.until = self.brain.cursor
        self.last_steps = 0
        if self.nociception is not None:
            self.nociception.new_round(self.brain.cursor)

    def step(self, rgb, steps):
        if type(steps) is not int or steps <= 0:
            raise ValueError('Positive integer integration steps required')
        b = self.brain
        noc = self.nociception
        active = min(steps, max(0, self.until - b.cursor))
        cuts = {0, active, steps}
        if noc is not None:
            noc.begin_tic()
            cuts.update(noc.boundaries(b.cursor, steps))
        edges = sorted(cuts)
        counts = np.zeros(b.n, dtype=np.int32)
        wall = 0.
        # Split at every exact pulse boundary, including inside a 35 Hz game tic.
        for start, end in zip(edges, edges[1:]):
            n = end - start
            pulses = []
            if start < active:
                pulses.append((b.circuit['dan'], 4.))
            if noc is not None:
                amplitude = noc.amplitude(b.cursor)
                if amplitude > 0:
                    pulses.append((noc.indices, amplitude))
                    noc.deliver(n, amplitude)
            stimulus = None if not pulses else pulses[0] if len(pulses) == 1 else pulses
            c, t = b.rgb_step(rgb, n*.1, learning=self.enabled, stimulation=stimulus)
            counts += c
            wall += t
        b.counts[:] = counts
        self.last_steps = active
        self.delivered_steps += active
        return counts, wall

    def observe(self, before, after):
        damage = max(0, before['health'] - max(0, after['health']))
        if damage:
            if after['finished']:
                self.terminal_events += 1
            else:
                self.events += 1
                if self.ppl101_pulse:
                    # Repeated hits extend the pulse; dose is measured, not inferred
                    # by multiplying event count. Duration = 2,000 x 0.1 ms.
                    self.until = self.brain.cursor + 2000
        if self.nociception is not None:
            self.nociception.observe(before, after, self.brain.cursor)
        return damage

    def telemetry(self):
        b = self.brain
        m = b.memory()
        ratios = b.weight[b.circuit['edges']] / b.baseline_plastic
        if not np.isfinite(ratios).all():
            raise RuntimeError('Nonfinite memory efficacy')
        out = {**m, 'enabled': self.enabled, 'validated': False,
            'maximum_efficacy': float(ratios.max()),
            'mean_absolute_change': float(np.abs(ratios-1).mean()),
            'bound_edges': int(np.count_nonzero((ratios <= .10001) | (ratios >= 1.99999))),
            'efficacy_histogram': np.histogram(ratios, bins=20, range=(.1, 2.))[0].tolist(),
            'histogram_range': [.1, 2.],
            'damage_input': self.damage_input, 'ppl101_damage_pulse': self.ppl101_pulse,
            'damage_events': self.events, 'delivered_ms': round(self.delivered_steps*.1, 3),
            'stimulus_active': self.last_steps > 0, 'stimulus_steps_last_tic': self.last_steps,
            'terminal_events_excluded': self.terminal_events,
            'cancelled_ms_at_round_reset': round(self.cancelled_steps*.1, 3),
            'KC_spikes_last_tic': int(b.counts[b.circuit['kc']].sum()),
            'DAN_spikes_last_tic': b.counts[b.circuit['dan']].tolist(),
            'MBON_spikes_last_tic': b.counts[b.circuit['mb']].tolist()}
        if self.nociception is not None:
            out['nociception'] = {**self.nociception.telemetry(),
                'stimulated_spikes_last_tic': int(b.counts[self.nociception.indices].sum())}
        return out


REINFORCEMENT = {
    'ppl101': 'Nonfatal damage: next-step +4 mV-equivalent PPL101 current for 200 ms. Overlapping hits extend exposure. Terminal damage excluded; pending exposure cancelled at reset.',
    'none': 'No neural damage input. Health loss reaches the network only through the rendered game image. No PPL101 damage pulse, no nociceptor drive, no damage reward.',
    'snxx29': 'Simulated nociception: health loss drives the 20 identified SNxx29 leg sensory neurons through an artificial transducer (see nociception parameters). Fatal damage included; pulses continue across arena resets. No PPL101 damage pulse (calibrated tonic background retained) and no damage reward.',
    'random-matched': 'Control: health loss drives 20 leg sensory neurons matched to SNxx29 for side, transmitter and outgoing synapses, with the same transducer. No PPL101 damage pulse and no damage reward.',
    'random-dose-matched': 'Control: the same matched leg sensory neurons as random-matched, with the transducer gain calibrated so their spike rate matches SNxx29 at the SNxx29 gain. No PPL101 damage pulse and no damage reward.',
    'snch01': 'Milestone 5: health loss drives the 35 identified SNch01 abdominal sensory neurons through an artificial transducer. SNch01 is the connectomically best-supported (not confirmed) proxy for the published ppk+/c4da abdominal multidendritic (md) nociceptors. Fatal damage included; pulses continue across arena resets. No PPL101 damage pulse and no damage reward.',
    'snch01-random-matched': 'Control: health loss drives 35 abdominal sensory neurons matched to SNch01 for side, transmitter and outgoing synapses, with the same transducer. No PPL101 damage pulse and no damage reward.',
    'snch01-random-dose-matched': 'Control: the same matched abdominal sensory neurons as snch01-random-matched, with the transducer gain calibrated so their spike rate matches SNch01 at the SNch01 gain. No PPL101 damage pulse and no damage reward.',
}


def candidate_provenance(brain, root, training=None):
    paths = []
    for directory in ['doom_learning', 'doom_learning_v6']:
        paths += list((root/directory).glob('*.py')) + list((root/directory).glob('*.cpp'))
    from doom_learning_v6.brain import PARAMETERS
    damage_input = training.damage_input if training is not None else 'ppl101'
    record = {'model': 'adaptive-centered-v6-live-v1', 'validated': False,
        'kernel': brain.build, 'parameters': {**PARAMETERS, 'eta': brain.eta},
        'configuration': brain.configuration_signature(), 'calibration': brain.calibration,
        'visual': brain.visual_report, 'circuit': brain.circuit['report'],
        'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'reinforcement': REINFORCEMENT[damage_input],
        'rounds': 'Continuous fast neural state, efficacy state and memory traces across normal game resets; no per-round equilibration. Different from the historical isolated-trial pilot.',
        'claim': 'Experimental plasticity is enabled. Useful vision, associative learning and survival improvement have not been established.'}
    # The upstream record stays byte-identical so existing checkpoints still resume.
    if damage_input != 'ppl101':
        record['damage_input'] = damage_input
        record['claim'] = 'Simulated nociception experiment, not pain. Propagation, behavioral effects and learning have not been established.'
        if training.nociception is not None:
            record['nociception'] = {**training.nociception.parameters(), 'population': training.nociception.report}
    return record
