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
| Random control, same drive | `random-matched --nociception-seed N` | none | 20 matched leg sensory cells, SNxx29 gain |
| Random control, same spike dose | `random-dose-matched --nociception-seed N` | none | same 20 cells, calibrated gain |

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
- Defaults: `damage_reference = 20 HP`, and `gain = 30 mV-eq`. That is the
  lowest swept gain at which both strongest ascending partners (AN05B004,
  AN09B018) respond. The resting-to-threshold gap is 7 mV; SNxx29 stayed silent
  at 5 and 7.5 mV-eq.
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
synapses. In `random-matched` the stimulated cells get identical drive,
duration and timing.

Equal drive is not equal spike dose. SNxx29 sits in a feedback loop: its most
responsive ascending partner, AN05B004, is also its largest inhibitory input
(weight 838 of 1,185 incoming inhibition). Driven SNxx29 therefore fire far
less than the control cells at the same drive: 7.6 Hz against 77 Hz at
20 mV-eq.

`random-dose-matched` reuses the same cells, but with a gain calibrated on the
equilibrated brain so single-pulse population rates match SNxx29 at the SNxx29
gain:

```sh
python -m doom.nociception_probe --calibrate-dose   # → outputs/doom/nociception/dose-calibration-v1.json
```

The server refuses a calibration record made for another seed, pulse duration
or decay. Same-drive and same-dose controls answer different questions, and
both are kept.

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

Automated run of every condition: frozen weights, shared seeds, fixed neural
time, then the analysis.

```sh
python -m doom.nociception_experiment --out outputs/doom/nociception/m4-v1 --neural-seconds 600
```

Each condition is a separate `doom.server --max-neural-seconds` process. It
writes `run-<id>.json`, which records the fork and upstream commits and every
argument, and `run-<id>-end.json`, which records the end reason, ticks, neural
and game time, deaths and final weight hash. Conditions run in parallel only
while enough memory stays free. Completed conditions are skipped on restart,
and an interrupted attempt is kept aside as `<condition>.incomplete-*`.

Individual runs and the analysis can also be invoked directly:

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

### Probe v1 (gain 20 mV-eq, commit 68841cd, `outputs/doom/nociception/probe-snxx29-v1`)

Five 200 ms pulses on a gray frame; values are arm minus sham, per cell.

- SNxx29 fired +5 Hz in the first 50 ms and +8.5 Hz for the rest of the pulse.
- AN05B004 responded on every pulse: +26 Hz at onset and +20 Hz during the
  pulse, with first divergence at 10 ms. It is the only consistent ascending
  response at this gain.
- AN09B018, the strongest anatomical partner, was not recruited at 20 mV-eq. In
  the single-pulse sweep it reached 8 Hz at 30 mV-eq and 41 Hz at 40 mV-eq.
- AN17A018 and AN05B097 did not respond, and ANXXX196 responded only weakly.
- DAN, PPL1, PAM, MBON, KC and descending populations changed immediately in
  every arm, the random arm included, with mixed signs and per-pulse ranges
  spanning zero. After the first pulse the "pre" windows also differ.
  - This is divergence of the deterministic recurrent network, not a specific
    nociceptive DAN or DN response.
  - First-divergence latency is meaningful only for small direct partners.
- The dose check failed at equal drive: SNxx29 fired at 7.6 Hz and the
  same-drive random cells at 77 Hz. This led to the dose-matched control and
  the 30 mV-eq default.

Probe v1 establishes no endogenous dopamine response and no behavioral effect.

### Dose calibration (commit 33c7b6d, `outputs/doom/nociception/dose-calibration-v1.json`)

Single 200 ms pulse from the equilibrated brain, gray frame, seed 41027:

| Arm | Gain | Population rate during the pulse |
| --- | --- | --- |
| SNxx29 | 30 mV-eq | 26.25 Hz |
| Matched random cells | 30 mV-eq (same drive) | 116.5 Hz |
| Matched random cells | 9.5 mV-eq (`random-dose-matched`) | 25.5 Hz |

- The rate error at 9.5 mV-eq is 2.9%.
- The search was monotonic from 7 to 30 mV-eq.
- The match holds for one full-damage pulse on one state and frame. In game,
  hit size and network state still change the dose.

### Probe v2 (gain 30 mV-eq, commit 33c7b6d, `outputs/doom/nociception/probe-snxx29-v2`)

The protocol is the same as v1, with four arms. Values are arm minus sham
during the 50–200 ms part of the pulse, as a mean across 5 pulses, with the
per-pulse range in brackets.

| Group | SNxx29 (30 mV-eq) | Random, same drive (30) | Random, same dose (9.5) |
| --- | --- | --- | --- |
| Stimulated cells | +28.1 Hz (25.9 Hz during pulses) | +118.7 Hz (116.6) | +28.8 Hz (26.3) |
| AN05B004 | **+43.3 [+36.7, +53.3]** | +0.7 [−6.7, +10.0] | −2.0 [−6.7, +6.7] |
| AN09B018 | **+8.5 [+6.7, +12.5]**, 5/5 pulses, 40 ms | 0 | 0 |
| ANXXX196 | **+10.0 [+10.0, +10.0]**, 5/5 pulses | 0 | 0 |
| AN05B097 | +1.7 [+0.8, +2.5], 5/5 pulses | 0 | 0 |
| AN17A018 | 0 | 0 | 0 |
| All ascending neurons | +0.13 [−0.0, +0.4] | +0.06 | −0.02 |
| DAN / PAM / MBON / KC | mixed sign, ranges span zero | same | same |
| PPL101 (0–50 ms) | +20 [−10, +30] | +8 [−10, +30] | +12 [0, +30] |
| DNp20 / DNpe017 | mixed sign, ranges span zero | same | same |

- The dose match held across all five pulses: 25.85 Hz for SNxx29 and 26.3 Hz
  for the dose-matched cells.
- **Topology-specific ascending recruitment:** SNxx29 drove four of its
  anatomical ascending partners on every pulse. Neither random control did,
  not at the same spike dose and not at 4.5× that dose.
  - This is the first model evidence for the SNxx29 → ascending neuron step.
  - It rests on one state, one frame and a deterministic simulation, so it is
    not a statistical sample.
- **No specific brain-level response:** dopaminergic, mushroom-body and
  descending populations changed in every arm, including the "pre" windows
  that follow earlier pulses, with signs and sizes that do not separate the
  arms.
  - The SNxx29 → ascending neuron → central brain → DAN/DN part of Milestone 3
    is therefore not demonstrated.
  - Endogenous DAN activation is not established.
- Decoded open-loop turn and forward changes were small and not consistent
  across arms. No behavioral effect is claimed; Milestone 4 needs closed-loop
  game runs.

### Live smoke test (gain 20 mV-eq, 91 s neural time, 14 rounds)

This run checked the plumbing only; it is not a result.

- 128 damage events reached SNxx29, with 0 ms of PPL101 damage pulse.
- 13 pulses spanned a respawn.
- `neural_ms` stayed continuous across 13 deaths.
- Every death produced a complete record in `lives.jsonl` and
  `death-snapshots.jsonl`, with all six offsets.

### Milestone 4 (gain 30 mV-eq, `outputs/doom/nociception/m4-v1`)

Five conditions, one brain each, 600 s of neural time, frozen weights, ViZDoom
seed 41027, no reward. 85 to 102 lives and 527 to 602 analyzed damage events per
condition; events whose window crosses a respawn are excluded.

Per life:

| Condition | Lives | Median survival | Damage/min | Kills/life |
| --- | --- | --- | --- | --- |
| `none` | 85 | 6.49 s | 921 | 0.91 |
| `ppl101` | 85 | 6.49 s | 921 | 0.91 |
| `random-dose-matched` | 95 | 6.00 s | 997 | 0.76 |
| `snxx29` | 101 | 5.66 s | 1045 | 0.57 |
| `random-matched` | 102 | 5.61 s | 1057 | 0.66 |

Peri-damage change against `none`, 0–200 ms after a nonfatal hit, bootstrap 95%
intervals; only intervals excluding zero are listed:

| Condition | Effect |
| --- | --- |
| `snxx29` | ascending neurons +1.51 [+0.64, +2.37] spikes/tic; DNp20 R−L +0.91 [+0.03, +1.81] Hz |
| `random-matched` | ascending +1.77 [+0.92, +2.63]; descending +1.34 [+0.48, +2.18]; forward −0.21 [−0.43, −0.00]; attack −0.019 [−0.04, −0.00]; DNpe017 −0.54 [−0.94, −0.13] at 200–1000 ms |
| `random-dose-matched` | none |
| `ppl101` | none |

**Milestone 4 is not demonstrated.** An immediate behavioral change that is
specific to nociception was not found:

- `snxx29` raises ascending-neuron activity in the live game, which confirms the
  probe, but its turn, forward and attack changes are indistinguishable from
  `none`.
- The same-drive random control, which fires 4.5 times more, produces *more*
  behavioral change than SNxx29. What moves behavior here is the amount of
  sensory drive, not nociceptive identity.
- At matched spike dose the random control produces nothing measurable, and
  SNxx29 keeps only the ascending-neuron response. That is the one effect that
  survives dose matching.
- No condition changed DAN activity: Milestone 8 stays negative in closed loop.
- Shorter survival in the stimulated conditions is not evidence of avoidance.
  It is consistent with extra sensory drive disturbing an already fragile
  controller.

**Control A equals Control B behaviorally.** Across all 21,000 tics, `ppl101`
and `none` produced identical actions, health and kills. Only the PPL101 spike
counts differ (+1,542 spikes). With frozen weights the upstream damage
mechanism cannot change behavior at all: the two dopamine cells use the
modulatory channel, which delivers no fast excitation and only feeds the
plasticity trace. Control A is therefore a meaningful comparison only once
plasticity is enabled (Milestone 6).

Limits: one run per condition and no seed replicates, so these are single
deterministic trajectories; ViZDoom also tints the screen on damage, so every
condition receives a visual damage cue.
