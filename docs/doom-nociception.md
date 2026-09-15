# Simulated nociception: Doom damage → SNxx29 (Milestones 1–4)

This fork adds a second sensory modality to the v6 candidate. Doom health loss
can enter the retained MaleCNS v1.0 graph through identified leg sensory
neurons instead of the upstream artificial PPL101 dopamine pulse. This is
**simulated nociception**, not pain, and nothing below establishes learning.

## Loop

```text
ViZDoom frame ─→ R1–R6 / R8 inputs ─┐
                                    ├─→ 166,700-neuron MaleCNS v1.0 ─→ DNp20 / DNpe017 ─→ fixed BCI ─→ ViZDoom
health loss ──→ transducer ─→ SNxx29┘
```

Death resets the arena, not the brain. Membrane state, synaptic queues,
eligibility, modulation traces, memory state, R1–R6/R8 filters and decoder
filters all continue across rounds; `simulation_age_ms` is the relevant
clock. There is no "death" input: the brain receives intense nociceptive drive
followed by the abrupt new-arena image.

## Conditions (`doom.server --model experimental-v6 --damage-input …`)

| Condition | `--damage-input` | Damage → PPL101 pulse | Damage → sensory drive |
| --- | --- | --- | --- |
| Control A, upstream | `ppl101` (default) | +4 mV-eq, 200 ms | none |
| Control B, no damage signal | `none` | none | none |
| Experiment | `snxx29` | none | 20 SNxx29 cells |
| Random control | `random-matched --nociception-seed N` | none | 20 matched leg sensory cells |

No condition has a damage reward (`--reward off` is required for v6). The
calibrated PPL101 tonic background (11.3125 mV-eq, baseline rate target) is
kept in every condition; it is not a damage signal. Without `--learning` the
KC→MBON11 weights stay frozen (Milestones 1–4). Upstream checkpoints and
provenance records for `ppl101` are unchanged; any other damage input is part
of the checkpoint identity and cannot resume a different condition.

## Measured circuitry (MaleCNS v1.0)

- Exact `type == "SNxx29"`: 20 neurons, 10 left / 10 right by `rootSide`
  (`somaSide` is empty for these nerve-entering cells), superclass
  `vnc_sensory`, subclass `leg`, entering through ProLN, MesoLN and MetaLN.
  Four composite `SNxx27,SNxx29` bodies (two leg, two notum, transmitter
  unclear) are excluded.
- Cell-type transmitter prediction: acetylcholine, confidence 0.674. Individual
  predictions: 14 acetylcholine, 5 serotonin, 1 unclear. The model uses the
  consensus acetylcholine for all 20, so they are fast excitatory cells.
- Output: 35,140 synapses onto 1,140 partners; 46% to ascending neurons and
  49% to VNC intrinsic neurons. Strongest partner types: AN09B018, AN05B004,
  IN13B011, IN23B032, AN17A018.
- Every DNp20, DNpe017, PPL1, PAM, MBON and KC cell is within three synaptic
  steps; some are within two.
- Body IDs, types, sides and transmitter predictions are exported to
  `outputs/doom/nociception/populations-malecns_v1.json`
  (`python -m doom.nociception export`).

## Inferred, not measured

- The ppk+/Gr28b.d+ heat-nociceptor interpretation of SNxx29 comes from
  MANC-era annotation literature. MaleCNS v1.0 has no `receptorType` for these
  cells, and the MaleCNS paper (Berg et al.) does not describe SNxx29 or
  nociception. That source still has to be cited.
- Simultaneous bilateral activation of all 20 cells is a simplification. Doom
  reports only the size of the hit, not where on the body it landed.

## Engineering choices (not physiology)

```text
damage_delta      = max(previous_health - max(current_health, 0), 0)
damage_normalized = clip(damage_delta / damage_reference, 0, 1)
drive_mv          = gain * damage_normalized
```

- Drive is a mV-equivalent depolarization added to each selected cell for
  `pulse_ms` (default 200). It stays constant or decays with `decay_ms`
  (default 0).
- A new hit restarts the pulse at the larger of the remaining and the new
  drive.
- Fatal damage also produces drive, and a pulse continues across the arena
  reset. Each such overlap is counted (`pulses_spanning_respawn`).
- Defaults: `damage_reference = 20 HP`, and `gain = 20 mV-eq` pending the
  Milestone 3 sweep. The resting-to-threshold gap is 7 mV, so smaller drives
  never fire an unstimulated cell.
- None of these values is physiologically calibrated.

## Random control

For each SNxx29 cell, one draw is taken without replacement from the three
same-side leg sensory neurons closest in outgoing synapse count. Candidates are
superclass `vnc_sensory`, subclass `leg`, acetylcholine, non-modulatory, and
not SNxx29. Whole draws repeat from the seeded generator until total outgoing
synapses are within 10% of SNxx29.

SNxx29 is unusually strongly connected: 1,757 outgoing synapses per cell on
average, against a median of 176 in the pool. The two strongest left SNxx29
cells exceed every left candidate, so the control is matched on total output,
not cell by cell. With seed 41027 it reaches 90.5% of SNxx29's total outgoing
synapses. The stimulated cells get identical drive, duration and timing.

## Recording

- `audit.jsonl` and the hourly archive, per tic:
  - `learning.damage_input` and `learning.nociception` (drive, delivered dose,
    events, spikes of the stimulated cells)
  - `monitor`: spike sums for SNxx29, the top ascending partner types, all
    ascending neurons, DAN, PPL1, PAM, MBON, KC, descending neurons, DNp20 L/R
    and DNpe017
  - `simulation_age_ms`
  - `retina_change`: mean absolute change of the R1–R6 samples, which marks the
    respawn visual transient
- `lives.jsonl`, per round: survival, kills, hits, shots, damage, damage per
  minute, distance, mean turn and forward. Censored when the process stops.
- `death-snapshots.jsonl`: activity groups, DN rates and voltages, nociceptive
  drive, PPL101 state, filtered luminance and `retina_change` at −500, −100, 0,
  +100, +500 and +1,000 ms around the last pre-respawn tic. Also memory
  statistics, eligibility and decoder rates at death, plus a per-tic trace.
  `--death-snapshot-full` also saves whole-brain voltages.

All of this is observer telemetry. None of it reaches the decoder.

## Milestone 3: open-loop propagation probe

```sh
python -m doom.nociception_probe --gain-sweep 5,7.5,10,15,20,30,40
```

- No game runs. The full calibrated brain, with frozen weights, views a fixed
  frame.
- After a 2 s equilibration, one saved state seeds the sham, SNxx29 and
  random-matched arms, and each arm receives five jittered pulses.
- The simulation is deterministic, so arm-minus-sham differences are exact
  model responses for that state and frame, not samples of variability.
- Output: `outputs/doom/nociception/probe-snxx29-v1/report.json` and
  `series.npz`.

## Milestone 4: behavior around damage

```sh
python -m doom.server --model experimental-v6 --damage-input snxx29 --audit-dir outputs/doom/nociception/run-snxx29
python -m doom.analyze_nociception --run none=… --run snxx29=… --run random-matched=… --run ppl101=…
```

- For each nonfatal hit, the analysis compares the 0–200 ms and 200–1,000 ms
  after it with the preceding second: turn, forward, attack, DN rates and
  activity groups.
- Events whose window crosses a respawn are excluded.
- Conditions are compared against `none` with bootstrap 95% intervals.

**Caveat:** ViZDoom tints the screen when the player is hit, so every
condition, `none` included, receives a visual damage cue.

## Results

Recorded after the runs; negative results are kept.
