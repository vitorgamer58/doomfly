"""Per-life outcome log. Observer telemetry only; never passed to the decoder.

A life is one arena round. The brain keeps running across lives, so every
record carries simulation_age_ms (neural time since the brain started) in
addition to the episode number.
"""
import json
import math
from pathlib import Path


class LifeMetrics:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.current = None

    def start(self, observation, simulation_age_ms):
        self.current = {'episode': observation['episode'], 'start_simulation_age_ms': round(simulation_age_ms, 3),
            'start_kills': observation['kills'], 'start_hits': observation.get('hits'),
            'ticks': 0, 'damage_received': 0., 'damage_events': 0, 'shots': 0, 'attack_ticks': 0,
            'turn_abs_sum': 0., 'turn_sum': 0., 'forward_sum': 0., 'distance': 0., 'position': None,
            'kills': 0, 'hits': None}

    def tick(self, before, after, applied, spectator=None):
        c = self.current
        if c is None:
            return
        c['ticks'] += 1
        damage = max(0., float(before['health']) - max(0., float(after['health'])))
        c['damage_received'] += damage
        c['damage_events'] += int(damage > 0)
        c['shots'] += max(0, int(before['ammo']) - int(after['ammo']))
        c['attack_ticks'] += int(bool(applied['attack']))
        c['turn_abs_sum'] += abs(float(applied['turn']))
        c['turn_sum'] += float(applied['turn'])
        c['forward_sum'] += float(applied['forward'])
        c['kills'] = after['kills'] - c['start_kills']
        if c['start_hits'] is not None and after.get('hits') is not None:
            c['hits'] = after['hits'] - c['start_hits']
        if spectator is not None:
            position = (spectator['player']['x'], spectator['player']['y'])
            if c['position'] is not None:
                c['distance'] += math.dist(c['position'], position)
            c['position'] = position

    def finish(self, final, simulation_age_ms, *, censored=False, run_id=None):
        c = self.current
        if c is None or not c['ticks']:
            return None
        ticks = c['ticks']
        seconds = ticks/35
        record = {'run_id': run_id, 'episode': c['episode'], 'censored': censored, 'died': bool(final.get('finished')) and not censored,
            'start_simulation_age_ms': c['start_simulation_age_ms'], 'end_simulation_age_ms': round(simulation_age_ms, 3),
            'survival_ticks': ticks, 'survival_seconds': round(seconds, 4), 'kills': c['kills'], 'hits': c['hits'],
            'shots': c['shots'], 'attack_ticks': c['attack_ticks'], 'damage_received': c['damage_received'],
            'damage_events': c['damage_events'], 'damage_per_minute': round(c['damage_received']/seconds*60, 3),
            'distance_doom_units': round(c['distance'], 3), 'mean_abs_turn': round(c['turn_abs_sum']/ticks, 5),
            'mean_turn': round(c['turn_sum']/ticks, 5), 'mean_forward': round(c['forward_sum']/ticks, 5)}
        with self.path.open('a') as f:
            f.write(json.dumps(record, separators=(',', ':'))+'\n')
        self.current = None
        return record
