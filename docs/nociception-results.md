# Simulated nociception: results so far (Milestones 1–6)

Measured results for the SNxx29 and SNch01 damage pathways in the retained
MaleCNS v1.0 graph. Method, parameters and provenance are in
[`doom-nociception.md`](doom-nociception.md); this file records what came out.

State: Milestones 1–6 executed. Milestones 1-5 used frozen weights, no reward,
ViZDoom seed 41027. Milestone 6 (six task_atualizado.md section-25 arms A–F,
plasticity on except F, trimmed to 5,400 s neural time per arm) is complete;
results are in §9. Milestones 7–8 not started beyond the DAN checks in §4, §7
and §9.

---

## Summary

| Question | Answer |
| --- | --- |
| Does damage reach the identified nociceptors? | Yes. 128 to 602 damage events per run, delivered with measured dose |
| Does activity propagate SNxx29 → ascending neurons? | **Yes, and specifically.** Four partner types respond on every pulse; neither random control reproduces it. SNch01 (Milestone 5) shows the same pattern |
| Does it reach dopaminergic neurons? | **No, with frozen weights (Milestones 3-5).** With plasticity on (Milestone 6), yes for `ppl101` and, much more strongly, for the reset-on-death arm — but not for plain `snxx29` |
| Does it change behavior right after a hit? | With frozen weights: **no effect attributable to nociceptive identity**, drive amount explains what changes. With plasticity on: the reset-on-death arm is the only one with a clear immediate behavioral change |
| Does the brain survive death? | Yes. Neural state, filters and traces continue across every death (except the Control E arm, by design) |
| Does the network learn to survive better over many lives? | **Only the plain `snxx29` arm shows a clear improving trend** (survival +23%, damage/min −13%); the arm with the largest acute neural/DAN response (reset-on-death) shows no improvement |

---

## 1. Population identity (MaleCNS v1.0)

- Exact `type == "SNxx29"`: **20 neurons, 10 left / 10 right** by `rootSide`
  (`somaSide` is empty for these cells), superclass `vnc_sensory`, subclass
  `leg`, entering through ProLN, MesoLN and MetaLN. All 20 are retained in the
  166,700-neuron graph.
- Four composite `SNxx27,SNxx29` bodies were excluded: two leg, two notum,
  transmitter `unclear`.
- Cell-type transmitter prediction acetylcholine at 0.674 confidence. Per body:
  14 acetylcholine, 5 serotonin, 1 unclear. The model uses the consensus for all
  20, so they act as fast excitatory cells.
- Output: **35,140 synapses onto 1,140 partners; 46% to ascending neurons**,
  49% to VNC intrinsic neurons. Strongest partners: AN09B018, AN05B004,
  IN13B011, IN23B032, AN17A018.
- SNxx29 is unusually well connected: 1,757 outgoing synapses per cell on
  average against a median of 176 for leg sensory neurons generally.

Body IDs and per-neuron provenance: `outputs/doom/nociception/populations-malecns_v1.json`.

## 2. Gain calibration

Single 200 ms pulse from an equilibrated brain on a fixed gray frame. Rates are
per cell during the pulse.

| Gain (mV-eq) | SNxx29 | AN09B018 |
| --- | --- | --- |
| 5 | 0 (silent) | 0 |
| 7.5 | 0 (silent) | 0 |
| 10 | 1.5 Hz | 0 |
| 15 | 3.0 Hz | 0 |
| 20 | 8.5 Hz | 0.6 Hz |
| **30 (chosen default)** | **26.3 Hz** | **8.1 Hz** |
| 40 | 55.5 Hz | 41.3 Hz |

The model's resting-to-threshold gap is 7 mV, which is why nothing fires below
that. 30 mV-eq is the lowest swept gain recruiting both strongest ascending
partners.

## 3. Equal drive is not equal dose

At 20 mV-eq the SNxx29 population fired at **7.6 Hz** while the same-drive
matched random control fired at **77 Hz**; at 30 mV-eq the numbers are 26.3 Hz
against 116.5 Hz.

The cause is topological: **AN05B004, the partner that responds most strongly to
SNxx29, is also their largest inhibitory input** (weight 838 of 1,185 incoming
inhibition). SNxx29 sit inside a feedback-inhibition loop that the control cells
do not have.

A second control was therefore calibrated: `random-dose-matched` drives the same
cells at **9.5 mV-eq**, giving 25.5 Hz against SNxx29's 26.25 Hz, a 2.9% error.
Record: `outputs/doom/nociception/dose-calibration-v1.json`.

## 4. Milestone 3 — propagation (open loop, no game)

Five 200 ms pulses, fixed frame, frozen weights, all arms seeded from one
equilibrated state. Values are arm minus sham, per cell, during 50–200 ms of the
pulse, with the per-pulse range in brackets.
(`outputs/doom/nociception/probe-snxx29-v2`)

| Group | SNxx29 (30 mV-eq) | Random, same drive (30) | Random, same dose (9.5) |
| --- | --- | --- | --- |
| Stimulated cells | +28.1 Hz | +118.7 Hz | +28.8 Hz |
| **AN05B004** | **+43.3 [+36.7, +53.3]** | +0.7 [−6.7, +10.0] | −2.0 [−6.7, +6.7] |
| **AN09B018** | **+8.5 [+6.7, +12.5]**, 5/5, 40 ms | 0 | 0 |
| **ANXXX196** | **+10.0 [+10.0, +10.0]**, 5/5 | 0 | 0 |
| AN05B097 | +1.7 [+0.8, +2.5], 5/5 | 0 | 0 |
| AN17A018 | 0 | 0 | 0 |
| DAN / PAM / MBON / KC / DN | mixed sign, ranges span zero | same | same |

**Positive result:** SNxx29 drove four of its anatomical ascending partners on
every pulse, and neither random control did, not even at 4.5 times the spike
dose. This is topology-specific recruitment.

**Negative result:** central-brain, dopaminergic and descending populations
changed in every arm, including in the "pre" windows that follow earlier pulses.
That is divergence of a deterministic recurrent network, not a nociceptive
response. `SNxx29 → ascending → central brain → DN` is therefore **not**
demonstrated, and first-divergence latency is meaningful only for small direct
partners.

At 20 mV-eq (probe v1) only AN05B004 responded; AN09B018 was not recruited.

## 5. Milestone 4 — behavior in the game

Five conditions, one brain each, 600 s of neural time, 473 lives in total, 527
to 602 analyzed damage events per condition. Events whose window crosses a
respawn are excluded. (`outputs/doom/nociception/m4-v1`)

| Condition | Lives | Median survival | Damage/min | Kills/life |
| --- | --- | --- | --- | --- |
| `none` | 85 | 6.49 s | 921 | 0.91 |
| `ppl101` | 85 | 6.49 s | 921 | 0.91 |
| `random-dose-matched` | 95 | 6.00 s | 997 | 0.76 |
| `snxx29` | 101 | 5.66 s | 1045 | 0.57 |
| `random-matched` | 102 | 5.61 s | 1057 | 0.66 |

Peri-damage change against `none`, 0–200 ms after a nonfatal hit, bootstrap 95%
intervals. Only intervals excluding zero are listed:

| Condition | Effect |
| --- | --- |
| `snxx29` | ascending neurons **+1.51 [+0.64, +2.37]** spikes/tic; DNp20 R−L **+0.91 [+0.03, +1.81]** Hz |
| `random-matched` | ascending +1.77 [+0.92, +2.63]; descending +1.34 [+0.48, +2.18]; forward −0.21 [−0.43, −0.00]; attack −0.019 [−0.04, −0.00]; DNpe017 −0.54 [−0.94, −0.13] at 200–1000 ms |
| `random-dose-matched` | none |
| `ppl101` | none |

**Milestone 4 is not demonstrated.**

- SNxx29 raises ascending-neuron activity in the live game, confirming the
  probe. This is the one effect that survives dose matching.
- Turn, forward and attack are indistinguishable from `none`.
- The same-drive random control, firing 4.5 times more, is the only arm that
  moves behavior. What moves behavior is the amount of sensory drive, not
  nociceptive identity.
- No condition changed DAN activity, so Milestone 8 stays negative in closed
  loop as well.
- Shorter survival under stimulation is **not** evidence of avoidance. It is
  consistent with extra sensory drive disturbing an already fragile controller.

### 5.1 Control A is inert while weights are frozen

Across all **21,000 tics**, `ppl101` and `none` produced **identical actions,
health and kills**. The only difference is 1,542 extra spikes in the PPL101
cells themselves.

The reason is structural: in v6, modulatory cells deliver no fast excitation.
They only update the trace that feeds the plasticity rule, which is disabled
when weights are frozen. The upstream damage mechanism therefore cannot change
behavior in a frozen-weight experiment, and Control A only becomes an
informative comparison once plasticity is enabled (Milestone 6).

## 6. Continuity across death

Confirmed in every run: membrane state, synaptic queues, eligibility, modulation
traces, memory state, R1–R6/R8 filters and decoder filters continue across
deaths; only the pending PPL101 exposure is cancelled. In `snxx29`, 13 of the
nociceptive pulses in the smoke test spanned a respawn, by design: fatal damage
also drives the nociceptors, so the brain receives intense nociception followed
by the abrupt new-arena image rather than a "you died" signal.

## 7. Milestone 5 — SNch01 abdominal population (open loop)

The exclusion of SNch01 in the original protocol (`task.md` §12) was based on
VFB instances labelled as wing-margin gustatory bristles. The MANC systematic
annotation study (Cheong et al., eLife 2024, reviewed preprint 97766) instead
names SNch01 as the leading connectomic candidate for the published ppk+/class-IV
(c4da) abdominal md nociceptors, and groups it with SNxx29 in a connectivity
cluster plausibly related to aversive stimuli. In MaleCNS v1.0, all 35 SNch01
cells (18 R / 17 L by `rootSide`, all acetylcholine) carry `subclass == "abdomen"`
with no wing-margin contamination, resolving that conflict for this dataset. On
the "% of output to ascending neurons" ranking alone the best match would have
been SNpp02 (45.5%), but SNpp02 is a Wheeler's-organ proprioceptor, not a
nociceptor candidate; SNch01 is therefore used as the connectomically
best-supported, not confirmed, proxy for the md population.
(`outputs/doom/nociception/populations-malecns_v1.json`,
`outputs/doom/nociception/probe-snch01-v1/report.json`)

- **Gain calibration.** SNch01 recruits at much lower gain than SNxx29 (it sits
  outside SNxx29's AN05B004 feedback-inhibition loop): 16.1 Hz at 20 mV-eq,
  against SNxx29's 7.6 Hz at 20 and 26.3 Hz at 30. 20 mV-eq was chosen as the
  lowest swept gain clearly recruiting the known ascending partners (AN09B018
  6.9→21.9 Hz, AN05B004 65→95 Hz between 15 and 20 mV-eq).
- **Dose calibration.** The matched random abdominal control reaches SNch01's
  16.1 Hz rate at 8.25 mV-eq (15.3 Hz, 5.3% error).
  (`outputs/doom/nociception/dose-calibration-snch01-v1.json`)
- **Propagation, dose-matched.** Five 200 ms pulses, same open-loop probe design
  as Milestone 3. SNch01 drove four ascending partners on every pulse: **AN09B018
  +23.7 Hz, AN05B004 +52.0 Hz, ANXXX196 +96.7 Hz, ANXXX055 +24.0 Hz** (50–200 ms
  window, arm minus sham). Two of these (AN09B018, ANXXX196) are **zero** in the
  dose-matched random control; AN05B004 responds far more weakly (+4.0 Hz vs
  +52.0 Hz). This reproduces the SNxx29 pattern — topology-specific recruitment
  surviving dose matching — with a different, non-overlapping-except-in-strongest-
  partners population. AN01A021, SNch01's other strong weighted output partner,
  showed no measurable divergence in this probe.
- **DAN check.** No specific dopaminergic response, same as Milestone 3/4 for
  SNxx29. Milestone 8 stays negative for SNch01 at this gain as well.

## 8. Limits

- One run per condition/arm, no seed replicates. These are single deterministic
  trajectories, not samples of a distribution.
- ViZDoom tints the screen on damage, so every condition, `none` included,
  receives a visual damage cue. That is what Control B measures.
- The ppk+/Gr28b.d+ heat-nociceptor identity of SNxx29, and the ppk+/c4da md
  identity of SNch01, are both inferred from MANC-era literature, not confirmed
  in MaleCNS v1.0. Neither v1.0 annotation carries a `receptorType`, and the
  MaleCNS paper does not describe either population or nociception.
- The transducer from hit points to millivolts is an engineering choice. No
  value in it is physiologically calibrated, and the SNxx29 gain (30 mV-eq) and
  SNch01 gain (20 mV-eq) were calibrated independently and are not comparable
  to each other as "equal stimulus strength".
- Simultaneous bilateral stimulation of the whole population is a
  simplification; Doom reports only how much damage was taken, not where.
- Milestone 4/5 used 600 s of neural time per condition/arm; Milestone 6 uses
  up to 5,400 s per arm, still short relative to the plasticity rule's 1,800 s
  memory time constant (see below).

## 9. Milestone 6 — plasticity across many lives (six arms)

Six arms, each a continuous brain across ~830-930 lives, all trimmed to exactly
5,400 s of neural time for comparison (`max_simulation_age_ms` in
`outputs/doom/nociception/m6-v1/analysis.json`): `A_snxx29`, `B_random_dose_matched`,
`C_none`, `D_ppl101` (all `--learning`, state persists across death),
`E_snxx29_reset_on_death` (`--learning --reset-on-death`, dynamic neural state
reset at every death, learned weights/eligibility/modulation traces/visual
filters preserved), and `F_snxx29_no_learning` (frozen weights, a fresh run at
the same duration, not a reuse of the Milestone 4 run). `C_none` is the
reference condition. Peri-damage effects below are 0–200 ms and 200–1,000 ms
after a nonfatal hit, arm minus `C_none`, only where the 95% bootstrap
interval excludes zero.

**Note on duration.** Two out-of-memory kills interrupted this run twice. `A`,
`B`, `C`, `D` resumed past interruptions with `doom.server`'s per-process
`--max-neural-seconds` (a documented limitation: it counts time in the current
process, not a running total across resumes) and ended up with far more neural
time (8,656–9,102 s) than the 5,400 s target before the orchestrator caught up
and stopped them. `E` and `F` landed within ~9 s of the target. All six were
trimmed to the first 5,400 s for every statistic in this section; the extra
time for A-D is kept in the audit logs but excluded here.

### 9.1 SNxx29 with plasticity: propagation replicates, DAN does not respond

`A_snxx29` reproduces the Milestone 3/4 pattern under learning: SNxx29,
AN05B004, AN09B018 and ascending-neuron activity are all elevated after a hit
(0–200 ms: SNxx29 +4.34, AN05B004 +0.81, AN09B018 +0.22, ascending +1.14
spikes/tic). No DAN or MBON effect, and no behavioral effect (turn, forward,
attack indistinguishable from `C_none`). `F_snxx29_no_learning` shows the same
propagation pattern at similar magnitude, confirming this is the SNxx29→ascending
route itself, not something plasticity adds.

### 9.2 Control E is the one arm with a measurable DAN response — and it learns worse

`E_snxx29_reset_on_death` is the standout result. Its peri-damage effects are an
order of magnitude larger and broader than every other arm's, and it is the
**only arm with a statistically significant DAN response** in this project so
far: DAN +1.11 spikes/tic (0–200 ms) and +1.46 (200–1,000 ms), both CIs well
clear of zero. MBON, ascending-neuron and descending-neuron activity also rise
sharply (ascending +5.4 to +5.9, descending +7.1 to +9.9 spikes/tic), and
`forward` (−0.36 to −0.47) and `attack` (−0.02) drop — the only arm with a
clear immediate behavioral change after a hit.

But E's learning curve is flat-to-negative: median survival across the run goes
5.96 s → 5.81 s (18 bins of ~300 s), damage/min rises 982 → 1,015, and mean
synaptic efficacy stays low and roughly flat (0.68 → 0.68, versus 0.90 → 0.97
for `A_snxx29`). `A_snxx29`, by contrast, has no significant DAN response but
the best learning curve of any arm: survival 5.74 s → 7.09 s (+23%), damage/min
1,023 → 885 (−13%).

That is a dissociation worth flagging rather than resolving here: the arm whose
dynamic state resets at every death produces the largest acute neural response
to damage, including the only DAN signal seen in this project, but shows no
net improvement over the run; the arm that keeps its dynamic state continuous
shows real improvement with no comparable acute response. This is consistent
with (not proof of) the hypothesis that continuity of dynamic neural state
across deaths matters for translating an acute response into learning, but a
single run per arm cannot separate that from other differences between A and E
(e.g. E's lower steady-state efficacy could itself change how strongly damage
drives the network on each life).

### 9.3 PPL101 is no longer inert once plasticity is on

Milestone 4 found `ppl101` behaviorally and neurally inert against `none` with
frozen weights. With plasticity on, `D_ppl101` now shows a real DAN response
(+0.15 spikes/tic, 0–200 ms), an MBON change (−0.08), and small but significant
`turn`/DNp20 R−L effects at 200–1,000 ms. This is expected given the mechanism
(PPL101 only updates a plasticity trace, which does nothing while weights are
frozen), but it is the first evidence in this project that the historical
PPL101-mediated pathway can move the network once the modulatory signal has
something to act on.

### 9.4 Random-matched control (B) also moves behavior, and its learning curve is the worst

`B_random_dose_matched` (SNxx29-matched spike dose in unrelated cells) shows a
small `attack` decrease (−0.006, 0–200 ms) and `turn`/DNp20 R−L effects at
200–1,000 ms — a different, smaller footprint than A. Its learning curve is
also the only one that gets worse: survival flat (5.63 s → 5.63 s) but
damage/min rises 1,029 → 1,068, and it ends with the highest mean efficacy of
any arm (1.06, above the unpotentiated baseline of 1.0) while surviving no
better. Consistent with Milestone 4, dose without nociceptive identity is not
harmless, and here it does not translate into improvement either.

### 9.5 Summary table

| Arm | DAN response? | Behavioral peri-damage effect? | Survival trend (first→last bin) | Damage/min trend |
| --- | --- | --- | --- | --- |
| A_snxx29 | No | No | 5.74s → 7.09s (better) | 1023 → 885 (better) |
| B_random_dose_matched | No (small, opposite direction) | Yes (turn, attack) | 5.63s → 5.63s (flat) | 1029 → 1068 (worse) |
| C_none (reference) | — | — | 5.80s → 6.03s (better) | 1043 → 987 (better) |
| D_ppl101 | **Yes** | Yes (turn) | 5.84s → 6.17s (better) | 1016 → 941 (better) |
| E_snxx29_reset_on_death | **Yes (largest)** | **Yes (forward, attack)** | 5.96s → 5.81s (worse) | 982 → 1015 (worse) |
| F_snxx29_no_learning | n/a (frozen) | No | 5.90s → 5.83s (flat) | 994 → 1059 (worse) |

Full data: `outputs/doom/nociception/m6-v1/analysis.json` (peri-damage,
bootstrap 95% CIs) and `outputs/doom/nociception/m6-v1/learning-curves.json`
(300 s bins by `simulation_age`).

## 10. Open questions

1. Why does resetting dynamic neural state at death (E) produce the only
   significant DAN response and the largest peri-damage effects, yet show no
   improving survival/damage trend, while plain `snxx29` (A) shows the
   opposite pattern (no DAN response, best learning trend)? §9.2 is a
   dissociation, not an explanation. A repeat with seed replicates, and a
   variant that resets state but not eligibility traces (the "E2" arm the
   protocol anticipates), would help separate these.
2. Does the SNch01 pathway (Milestone 5) show the same E-vs-A dissociation
   under plasticity, or does its different topology (no AN05B004 feedback
   inhibition) change the outcome?
3. Every Milestone 6 result is one run per arm, no seed replicates. The
   dissociation in §9.2 and the direction of each learning curve could be
   seed-dependent; nothing here should be read as a robust effect size.
4. The plasticity rule's memory decays with a 1,800 s neural time constant,
   roughly 30 simulated minutes. Milestone 6's 5,400 s per arm covers three
   such time constants, but the arms still differ from each other's baseline
   mean efficacy (e.g. E: 0.68 vs A: 0.90-0.97) in ways not yet explained by
   the nociceptive condition alone.
5. Does a higher gain, or the SNch01 pathway, reach the dopaminergic neurons
   under frozen weights? SNch01 showed no specific DAN response in the
   open-loop probe (Milestone 5), matching SNxx29's frozen-weight result.
