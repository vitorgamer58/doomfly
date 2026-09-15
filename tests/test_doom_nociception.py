import json
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from doom.nociception import NociceptiveTransducer, select_population, snxx29_indices, MATCH_TOLERANCE
from doom.training import DamageTraining, candidate_provenance
from doom.life_metrics import LifeMetrics
from doom.death_snapshots import DeathSnapshots, OFFSETS_MS
from doom.monitor import ActivityMonitor, activity_groups

ROOT = Path(__file__).resolve().parents[1]
RGB = np.zeros((2, 2, 3), dtype=np.uint8)


def fake_connectome():
    rows = []
    def add(**kw):
        base = {'type': '', 'class': 'unknown_sensory', 'superclass': 'vnc_sensory', 'subclass': 'leg',
                'rootSide': 'L', 'somaSide': None, 'entryNerve': 'ProLN', 'out': 100, 'nt': 'acetylcholine'}
        rows.append({**base, **kw})
    for i in range(20):
        add(type='SNxx29', rootSide='L' if i < 10 else 'R', out=900 + 60*i)
    add(type='SNxx27,SNxx29', superclass='sensory_ascending', out=1500, nt='unclear')
    for side in 'LR':
        for j in range(60):
            add(type=f'SNta{j:02d}', rootSide=side, out=600 + 40*j)
    add(type='SNppl', rootSide='L', out=1500, nt='dopamine')  # ideal degree, but modulatory
    add(type='INgaba', superclass='vnc_intrinsic', subclass=None, out=1500, nt='gaba')
    add(type='DNp20', superclass='descending_neuron', subclass=None, rootSide=None, somaSide='L')
    add(type='DNp20', superclass='descending_neuron', subclass=None, rootSide=None, somaSide='R')
    frame = pd.DataFrame(rows)
    frame.index = pd.Index(np.arange(5000, 5000 + len(frame)), name='bodyId')
    transmitter = frame.pop('nt').to_numpy()
    outgoing = frame.pop('out').to_numpy()
    modulation = np.isin(transmitter, ['dopamine', 'octopamine', 'serotonin']).astype(np.uint8)
    return frame, transmitter, outgoing, modulation


def population(indices, source='snxx29'):
    return {'source': source, 'indices': np.asarray(indices),
            'report': {'seed': None, 'neurons': [{'body_id': str(i)} for i in indices]}}


class RecordingBrain:
    def __init__(self, n=40):
        self.n = n; self.cursor = 0; self.circuit = {'dan': np.array([2])}
        self.calls = []; self.counts = np.zeros(n, dtype=np.int32)

    def rgb_step(self, rgb, ms, learning, stimulation):
        steps = round(ms*10)
        pulses = [] if stimulation is None else stimulation if isinstance(stimulation, list) else [stimulation]
        self.calls.append((self.cursor, steps, [(tuple(np.asarray(i).tolist()), float(a)) for i, a in pulses]))
        self.cursor += steps
        c = np.zeros(self.n, dtype=np.int32)
        for i, _ in pulses:
            c[np.asarray(i)] += steps
        return c, 0.


def test_snxx29_uses_exact_type_and_root_side():
    a, tx, out, _ = fake_connectome()
    ix = snxx29_indices(a, tx)
    assert len(ix) == 20 and set(a.type.iloc[ix]) == {'SNxx29'}
    p = select_population('snxx29', a, tx, out)
    assert p['report']['sides'] == {'L': 10, 'R': 10} and p['report']['seed'] is None
    assert {r['dataset'] for r in p['report']['neurons']} == {'male-cns'}
    assert all(r['side'] in 'LR' and r['body_id'].isdigit() for r in p['report']['neurons'])
    with pytest.raises(ValueError, match='10 left'):
        snxx29_indices(a.iloc[1:], tx[1:])


def test_random_control_is_deterministic_side_balanced_and_degree_matched():
    a, tx, out, mod = fake_connectome()
    first = select_population('random-matched', a, tx, out, seed=7, modulation_mask=mod)
    again = select_population('random-matched', a, tx, out, seed=7, modulation_mask=mod)
    other = select_population('random-matched', a, tx, out, seed=8, modulation_mask=mod)
    np.testing.assert_array_equal(first['indices'], again['indices'])
    assert not np.array_equal(first['indices'], other['indices'])
    ix = first['indices']
    assert first['report']['sides'] == {'L': 10, 'R': 10} and len(np.unique(ix)) == 20
    assert not a.type.iloc[ix].str.contains('SNxx29').any()
    assert set(tx[ix]) == {'acetylcholine'} and not mod[ix].any()
    reference = snxx29_indices(a, tx)
    assert abs(out[ix].sum()/out[reference].sum() - 1) <= MATCH_TOLERANCE
    with pytest.raises(ValueError, match='seed'):
        select_population('random-matched', a, tx, out)


def test_transducer_math_is_explicit_and_clipped():
    t = NociceptiveTransducer(population([0, 1]), gain=20, damage_reference=20)
    assert t.observe({'health': 100}, {'health': 90, 'finished': False}, 0) == 10
    assert t.observe({'health': 30}, {'health': -10, 'finished': True}, 0) == 20
    assert t.observe({'health': 50}, {'health': 60, 'finished': False}, 0) == 0
    assert t.events == 2 and t.terminal_events == 1 and t.damage_total == 40
    for bad in [dict(gain=0), dict(gain=5, pulse_ms=0), dict(gain=5, decay_ms=-1), dict(gain=5, damage_reference=0),
                dict(gain=math.nan), dict(gain=5, left_right_mode='lateralized')]:
        with pytest.raises(ValueError):
            NociceptiveTransducer(population([0]), **bad)


def test_overlap_keeps_larger_drive_and_decay_splits_bins():
    t = NociceptiveTransducer(population([0]), gain=20, damage_reference=20, decay_ms=100)
    t.observe({'health': 100}, {'health': 80}, 0)
    assert t.amplitude(1000) == pytest.approx(20*math.exp(-1))
    t.observe({'health': 80}, {'health': 78}, 1000)  # small hit: remaining drive dominates
    assert t.amplitude(1000) == pytest.approx(20*math.exp(-1)) and t.until == 3000
    assert t.boundaries(2900, 286) == [100]
    assert t.boundaries(1000, 286) == [100, 200]
    assert t.amplitude(3000) == 0 and t.boundaries(3000, 286) == []


def test_nociceptive_pulse_is_exact_crosses_respawn_and_never_touches_ppl101():
    b = RecordingBrain()
    noc = NociceptiveTransducer(population([5, 6]), gain=15, damage_reference=20)
    t = DamageTraining(b, False, damage_input='snxx29', nociception=noc)
    t.step(RGB, 286)
    assert b.calls[-1][2] == []
    t.observe({'health': 100}, {'health': 0, 'finished': True}, )
    t.new_round()
    assert noc.spans_respawn == 1 and noc.until == 286 + 2000
    for _ in range(8):
        c, _ = t.step(RGB, 286)
    assert noc.delivered_steps == 2000 and t.delivered_steps == 0
    assert noc.delivered_dose == pytest.approx(15*200)
    stimulated = [(n, p) for _, n, p in b.calls if p]
    assert {p[0] for _, p in stimulated} == {((5, 6), 15.)}
    assert all((2,) not in [i for i, _ in p] for _, p in stimulated)
    assert stimulated[-1][0] == 2000 - 286*6


def test_none_input_counts_damage_without_any_stimulation():
    b = RecordingBrain(); t = DamageTraining(b, False, damage_input='none')
    t.observe({'health': 100}, {'health': 70, 'finished': False})
    for _ in range(4):
        t.step(RGB, 286)
    assert t.events == 1 and t.delivered_steps == 0 and all(not p for _, _, p in b.calls)
    assert 'nociception' not in t.state()


def test_snxx29_and_random_arms_receive_identical_dose_schedule():
    schedules = []
    for source, cells in [('snxx29', [1, 3]), ('random-matched', [7, 9])]:
        b = RecordingBrain()
        noc = NociceptiveTransducer(population(cells, source), gain=25, damage_reference=20, decay_ms=50)
        t = DamageTraining(b, False, damage_input=source, nociception=noc)
        for health in [(100, 85), (85, 60), (60, 60)]:
            t.observe({'health': health[0]}, {'health': health[1], 'finished': False})
            for _ in range(3):
                t.step(RGB, 286)
        schedules.append(([(start, n, [a for _, a in p]) for start, n, p in b.calls], noc.delivered_dose, noc.delivered_steps))
    assert schedules[0] == schedules[1]


def test_damage_input_configuration_is_validated_and_checkpointed():
    b = RecordingBrain()
    with pytest.raises(ValueError):
        DamageTraining(b, damage_input='snxx29')
    with pytest.raises(ValueError):
        DamageTraining(b, damage_input='ppl101', nociception=NociceptiveTransducer(population([1]), gain=5))
    with pytest.raises(ValueError):
        DamageTraining(b, damage_input='random-matched', nociception=NociceptiveTransducer(population([1]), gain=5))
    noc = NociceptiveTransducer(population([1]), gain=5)
    t = DamageTraining(b, False, damage_input='snxx29', nociception=noc)
    t.observe({'health': 100}, {'health': 90, 'finished': False}); t.step(RGB, 286)
    saved = t.state()
    other = DamageTraining(b, False, damage_input='snxx29', nociception=NociceptiveTransducer(population([1]), gain=5))
    other.restore(saved)
    assert other.state() == saved
    with pytest.raises(ValueError):
        other.restore({k: v for k, v in saved.items() if k != 'nociception'})
    with pytest.raises(ValueError):
        other.restore({**saved, 'nociception': {**saved['nociception'], 'peak': -1.}})
    upstream = DamageTraining(b, False)
    with pytest.raises(ValueError):
        upstream.restore(saved)


def toy_v6(directory):
    """Four-neuron v6 brain: node 0 excites node 1 through a strong existing edge."""
    from test_doom_learning_v6 import brain
    directory.mkdir()
    b = brain(directory)
    b.rgb_step = lambda rgb, ms, **kwargs: b.step([], ms, lamina_bias=0, **kwargs)
    return b


def test_nociceptor_drive_propagates_and_death_does_not_reset_the_brain(tmp_path):
    results = {}
    for source in ['none', 'snxx29']:
        brain = toy_v6(tmp_path/source)
        # Node 0 is an adapting toy KC resting at -60 mV; 80 mV-eq drives it hard enough to excite node 1.
        noc = NociceptiveTransducer(population([0]), gain=80, damage_reference=20) if source == 'snxx29' else None
        t = DamageTraining(brain, False, damage_input=source, nociception=noc)
        t.step(RGB, 286)
        t.observe({'health': 100}, {'health': 60, 'finished': False})
        total = np.zeros(brain.n, dtype=np.int32)
        for _ in range(7):
            c, _ = t.step(RGB, 286); total += c
        before = {k: getattr(brain, k).copy() for k in ['weight', *brain.fields]}
        cursor = brain.cursor
        t.new_round()
        assert brain.cursor == cursor
        for k, v in before.items():
            np.testing.assert_array_equal(v, getattr(brain, k), err_msg=k)
        results[source] = total
    assert results['none'][1] == 0 and results['snxx29'][0] > 0 and results['snxx29'][1] > 0


def test_provenance_keeps_upstream_record_and_labels_nociception():
    brain = SimpleNamespace(build='k', eta=.001, configuration_signature=lambda: {}, calibration={},
                            visual_report={}, circuit={'report': {}})
    upstream = candidate_provenance(brain, ROOT)
    assert set(upstream) == {'model', 'validated', 'kernel', 'parameters', 'configuration', 'calibration',
                             'visual', 'circuit', 'source_sha256', 'reinforcement', 'rounds', 'claim'}
    assert upstream == candidate_provenance(brain, ROOT, DamageTraining(RecordingBrain(), False))
    noc = NociceptiveTransducer(population([4]), gain=12)
    record = candidate_provenance(brain, ROOT, DamageTraining(RecordingBrain(), False, damage_input='snxx29', nociception=noc))
    assert record['damage_input'] == 'snxx29' and record['nociception']['gain_mv'] == 12
    assert record['nociception']['body_ids'] == ['4'] and 'not pain' in record['claim']


def test_life_metrics_are_logged_per_life(tmp_path):
    lives = LifeMetrics(tmp_path/'lives.jsonl')
    lives.start({'episode': 1, 'kills': 0, 'hits': 0}, 1000.)
    pose = lambda x: {'player': {'x': x, 'y': 0.}}
    lives.tick({'health': 100, 'ammo': 50}, {'health': 80, 'ammo': 49, 'kills': 1, 'hits': 1},
               {'turn': 2., 'forward': 5., 'attack': True}, pose(0.))
    lives.tick({'health': 80, 'ammo': 49}, {'health': -20, 'ammo': 49, 'kills': 1, 'hits': 1, 'finished': True},
               {'turn': -1., 'forward': 0., 'attack': False}, pose(3.))
    record = lives.finish({'finished': True}, 1057.)
    assert record['died'] and record['survival_ticks'] == 2 and record['damage_received'] == 100
    assert record['damage_events'] == 2 and record['shots'] == 1 and record['kills'] == 1 and record['hits'] == 1
    assert record['distance_doom_units'] == 3 and record['mean_abs_turn'] == 1.5
    assert (tmp_path/'lives.jsonl').read_text().count('\n') == 1


def test_death_snapshots_cover_requested_offsets(tmp_path):
    shots = DeathSnapshots(tmp_path/'death.jsonl', full_dir=tmp_path/'full')
    tic = 1000/35
    written = []
    for k in range(200):
        ms = k*tic
        record = shots.record({'neural_ms': ms, 'groups': {'SNxx29': k}, 'retina_change': 0.}, np.full(3, k, np.float32))
        if record:
            written.append(record)
        if k == 70:
            shots.death({'episode': 2})
    assert len(written) == 1
    r = written[0]
    assert set(r['snapshots']) == {str(o) for o in OFFSETS_MS} and not r['truncated']
    for o in OFFSETS_MS:
        assert abs(r['snapshots'][str(o)]['offset_ms'] - o) <= tic/2 + 1e-2  # offsets are rounded to 1 us
    assert r['trace'][0]['offset_ms'] >= -500 and r['trace'][-1]['offset_ms'] <= 1000
    with np.load(tmp_path/'full'/r['full_voltage_file']) as v:
        assert set(v.files) == {f'v_{o}' for o in OFFSETS_MS}
    shots.death({'episode': 3})
    assert shots.close()['truncated']


def test_monitor_groups_record_spikes_only(tmp_path):
    a, _, _, _ = fake_connectome()
    groups = activity_groups(a, stimulated=[0, 1])
    assert list(groups)[0] == 'stimulated' and len(groups['SNxx29']) == 20
    assert len(groups['DNp20_L']) == 1 and len(groups['DNp20_R']) == 1
    monitor = ActivityMonitor(groups, a.index.to_numpy())
    counts = np.zeros(len(a), dtype=np.int32); counts[:20] = 1
    assert monitor.sums(counts)['SNxx29'] == 20 and monitor.sums(counts)['stimulated'] == 2
    assert monitor.report()['groups']['SNxx29']['neurons'] == 20


def test_damage_window_analysis_compares_within_event_changes(tmp_path):
    from doom.analyze_nociception import analyze
    def audit(label, turn_after):
        directory = tmp_path/label; directory.mkdir()
        health, lines = 100, []
        for tick in range(1, 400):
            if tick in (100, 250):
                health -= 10
            recent = any(0 < tick - hit <= 7 for hit in (100, 250))
            lines.append({'run_id': 'r', 'recorded_at_ms': tick, 'tick': tick, 'neural_ms': tick*1000/35, 'episode': 1,
                          'game': {'health': health, 'finished': False},
                          'applied': {'turn': turn_after if recent else 0., 'forward': 1., 'attack': False},
                          'readouts': [], 'monitor': {'SNxx29': 5 if recent else 0}, 'learning': {'damage_input': label}})
        (directory/'audit.jsonl').write_text('\n'.join(json.dumps(line) for line in lines)+'\n')
        return directory
    report = analyze({'none': audit('none', 0.), 'snxx29': audit('snxx29', 3.)})
    noc = report['conditions']['snxx29']
    assert noc['analyzed_events'] == 2 and noc['windows']['post_0_200']['abs_turn']['mean'] == pytest.approx(3)
    assert noc['windows']['post_200_1000']['abs_turn']['mean'] == pytest.approx(0)
    assert report['conditions']['none']['windows']['post_0_200']['abs_turn']['mean'] == 0
    difference = report['comparisons_vs_none']['snxx29']['post_0_200']['abs_turn']
    assert difference['difference'] == pytest.approx(3) and difference['ci95'][0] > 0


def test_dose_matched_control_reuses_cells_and_requires_matching_calibration(tmp_path):
    from doom.nociception import load_dose_calibration
    a, tx, out, mod = fake_connectome()
    same = select_population('random-matched', a, tx, out, seed=5, modulation_mask=mod)
    dose = select_population('random-dose-matched', a, tx, out, seed=5, modulation_mask=mod)
    np.testing.assert_array_equal(same['indices'], dose['indices'])
    assert dose['source'] == 'random-dose-matched' and 'calibrated' in dose['report']['selection_rule']
    path = tmp_path/'calibration.json'
    path.write_text(json.dumps({'schema': 1, 'seed': 5, 'pulse_ms': 200., 'decay_ms': 0., 'snxx29_gain_mv': 30.,
                                'snxx29_rate_hz': 26., 'random_dose_matched_gain_mv': 12.5, 'random_rate_hz': 25.5}))
    calibration = load_dose_calibration(path, seed=5, pulse_ms=200, decay_ms=0)
    assert calibration['random_dose_matched_gain_mv'] == 12.5 and len(calibration['sha256']) == 64
    for kwargs in [dict(seed=6, pulse_ms=200, decay_ms=0), dict(seed=5, pulse_ms=100, decay_ms=0), dict(seed=5, pulse_ms=200, decay_ms=50)]:
        with pytest.raises(ValueError):
            load_dose_calibration(path, **kwargs)
    with pytest.raises(ValueError, match='dose calibration'):
        NociceptiveTransducer(dose, gain=12.5)
    with pytest.raises(ValueError, match='dose calibration'):
        NociceptiveTransducer(same, gain=12.5, calibration=calibration)
    noc = NociceptiveTransducer(dose, gain=12.5, calibration=calibration)
    t = DamageTraining(RecordingBrain(), False, damage_input='random-dose-matched', nociception=noc)
    assert t.state()['nociception']['events'] == 0 and noc.parameters()['dose_calibration']['sha256'] == calibration['sha256']
    with pytest.raises(ValueError):
        DamageTraining(RecordingBrain(), False, damage_input='random-matched', nociception=noc)


@pytest.mark.parametrize('argv', [
    ['--damage-input', 'snxx29'],
    ['--model', 'experimental-v6', '--damage-input', 'random-dose-matched'],
    ['--model', 'experimental-v6', '--damage-input', 'random-dose-matched', '--nociception-seed', '3', '--nociception-gain', '12'],
    ['--model', 'experimental-v6', '--damage-input', 'snxx29', '--nociception-dose-calibration', 'x.json'],
    ['--model', 'experimental-v6', '--damage-input', 'random-matched'],
    ['--model', 'experimental-v6', '--damage-input', 'snxx29', '--nociception-seed', '3'],
    ['--model', 'experimental-v6', '--nociception-gain', '9'],
])
def test_server_rejects_inconsistent_damage_input(argv):
    from doom.server import parse_args
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_server_accepts_experimental_conditions():
    from doom.server import parse_args
    args = parse_args(['--model', 'experimental-v6', '--damage-input', 'random-matched', '--nociception-seed', '3',
                       '--nociception-gain', '25'])
    assert args.damage_input == 'random-matched' and args.nociception_gain == 25
    assert parse_args([]).damage_input == 'ppl101' and parse_args([]).nociception_gain == 30
    dose = parse_args(['--model', 'experimental-v6', '--damage-input', 'random-dose-matched', '--nociception-seed', '3'])
    assert dose.damage_input == 'random-dose-matched'


def test_server_fixed_duration_flag_is_validated():
    from doom.server import parse_args
    assert parse_args(['--max-neural-seconds', '600']).max_neural_seconds == 600
    assert parse_args([]).max_neural_seconds is None
    with pytest.raises(SystemExit):
        parse_args(['--max-neural-seconds', '0'])


def test_experiment_runner_commands_resume_and_preserve_failed_attempts(tmp_path):
    from doom.nociception_experiment import command, completed, prepare_directory
    snx = command('snxx29', tmp_path/'s', port=8811, neural_seconds=600, seed=41027, nociception_seed=7, python='py')
    assert snx[:3] == ['py', '-m', 'doom.server'] and '--nociception-seed' not in snx
    assert snx[snx.index('--max-neural-seconds') + 1] == '600' and snx[snx.index('--damage-input') + 1] == 'snxx29'
    rnd = command('random-dose-matched', tmp_path/'r', port=8813, neural_seconds=600, seed=41027, nociception_seed=7)
    assert rnd[rnd.index('--nociception-seed') + 1] == '7'
    partial = tmp_path/'none'; partial.mkdir()
    (partial/'audit.jsonl').write_text('{}\n')
    (partial/'run-a-end.json').write_text(json.dumps({'end_reason': 'stopped'}))
    assert not completed(partial)
    moved = prepare_directory(partial)
    assert moved is not None and moved.name.startswith('none.incomplete-') and (moved/'audit.jsonl').exists()
    done = tmp_path/'ppl101'; done.mkdir()
    (done/'run-b-end.json').write_text(json.dumps({'end_reason': 'max-neural-seconds'}))
    assert completed(done) and prepare_directory(done) is None


def test_population_report_is_strict_json_when_predictions_are_missing():
    a, tx, out, mod = fake_connectome()
    predictions = pd.DataFrame({'predicted_nt': ['acetylcholine', None], 'predicted_nt_confidence': [.8, float('nan')],
                                'celltype_predicted_nt': ['acetylcholine', None], 'celltype_predicted_nt_confidence': [.67, float('nan')]},
                               index=pd.Index([a.index[0], a.index[21]], name='body'))
    report = select_population('random-matched', a, tx, out, seed=3, modulation_mask=mod, predictions=predictions)['report']
    json.dumps(report, allow_nan=False)
    snx = select_population('snxx29', a, tx, out, predictions=predictions)['report']['neurons'][0]
    assert snx['predicted_nt_confidence'] == .8 and snx['celltype_predicted_nt'] == 'acetylcholine'
