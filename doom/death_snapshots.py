"""Neural records around avatar death. Recording only; nothing is reset.

Snapshots at -500, -100, 0, +100, +500 and +1000 ms of neural time around the
last pre-respawn tic let analyses separate the nociceptive response from the
visual transient caused by the new arena image (retina_change).
"""
import json
from collections import deque
from pathlib import Path
import numpy as np

OFFSETS_MS = (-500, -100, 0, 100, 500, 1000)
HISTORY_MS = 600


class DeathSnapshots:
    def __init__(self, path, *, full_dir=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.full_dir = Path(full_dir) if full_dir else None
        self.history = deque()
        self.pending = None
        self.written = 0

    def record(self, sample, voltage=None):
        """Store one tic sample (must contain 'neural_ms'); returns a finished record, if any."""
        item = (sample, voltage.copy() if self.full_dir is not None and voltage is not None else None)
        self.history.append(item)
        while self.history and sample['neural_ms'] - self.history[0][0]['neural_ms'] > HISTORY_MS:
            self.history.popleft()
        if self.pending is not None:
            self.pending['after'].append(item)
            if sample['neural_ms'] - self.pending['death_ms'] >= OFFSETS_MS[-1]:
                return self._write(truncated=False)
        return None

    def death(self, context):
        """Mark the most recently recorded sample as the moment of death."""
        finished = self._write(truncated=True) if self.pending is not None else None
        if not self.history:
            return finished
        death_ms = self.history[-1][0]['neural_ms']
        self.pending = {'death_ms': death_ms, 'before': list(self.history), 'after': [], 'context': context}
        return finished

    def close(self):
        return self._write(truncated=True) if self.pending is not None else None

    def _write(self, truncated):
        p = self.pending
        self.pending = None
        items = p['before'] + p['after']
        times = np.array([s['neural_ms'] for s, _ in items]) - p['death_ms']
        snapshots = {}
        voltages = {}
        for offset in OFFSETS_MS:
            if offset > times.max() or offset < times.min() - 1000/35:
                continue
            k = int(np.argmin(np.abs(times - offset)))
            snapshots[str(offset)] = {**items[k][0], 'offset_ms': round(float(times[k]), 3)}
            if items[k][1] is not None:
                voltages[f'v_{offset}'] = items[k][1]
        record = {'death_neural_ms': p['death_ms'], 'truncated': truncated, 'offsets_ms': list(OFFSETS_MS),
            **p['context'], 'snapshots': snapshots,
            'trace': [{'offset_ms': round(float(t), 3), **{k: s[k] for k in ['groups', 'retina_change', 'nociception_drive_mv', 'ppl101_active'] if k in s}}
                      for t, (s, _) in zip(times, items) if -500 - 1e-6 <= t <= 1000 + 1e-6]}
        if voltages:
            self.full_dir.mkdir(parents=True, exist_ok=True)
            name = f"death-{p['context'].get('episode', 'x')}-{int(p['death_ms'])}.npz"
            np.savez_compressed(self.full_dir/name, **voltages)
            record['full_voltage_file'] = name
        with self.path.open('a') as f:
            f.write(json.dumps(record, separators=(',', ':'))+'\n')
        self.written += 1
        return record
