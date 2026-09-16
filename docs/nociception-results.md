# Simulated nociception: results so far (Milestones 1–4)

Measured results for the SNxx29 damage pathway in the retained MaleCNS v1.0
graph. Method, parameters and provenance are in
[`doom-nociception.md`](doom-nociception.md); this file records what came out.

State: Milestones 1–4 executed. Milestones 5–8 not started. Every run below used
frozen weights, no reward, and the same ViZDoom seed (41027). Code at commit
`e3d2566` on branch `nociception-snxx29`.

---

## Summary

| Question | Answer |
| --- | --- |
| Does damage reach the identified nociceptors? | Yes. 128 to 602 damage events per run, delivered with measured dose |
| Does activity propagate SNxx29 → ascending neurons? | **Yes, and specifically.** Four partner types respond on every pulse; neither random control reproduces it |
| Does it reach dopaminergic neurons? | **No specific response measured** |
| Does it change behavior right after a hit? | **No effect attributable to nociceptive identity.** Drive amount explains what changes |
| Does the brain survive death? | Yes. Neural state, filters and traces continue across every death |

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

## 7. Exploratory: candidates for Milestone 5 (abdominal md)

The MaleCNS release has no cell type named "md". Abdominal sensory neurons in
the retained graph: 1,143, entering through AbN2, AbN3, AbN4, AbNT and ADMN.
Ranking them by the published md signature (~49% of output synapses to ascending
neurons):

| Type | Cells | Output synapses | Share to ascending | Nerve | Class |
| --- | --- | --- | --- | --- | --- |
| SNch01 | 35 | 57,689 | 47.2% | AbN4 | chemosensory |
| SNpp02 | 36 | 15,122 | 45.5% | AbN3 | mechanosensory_proprioceptive |
| SNxx22 | 34 | 10,955 | 33.8% | AbN2 | unknown_sensory |
| SNxx06 | 37 | 9,052 | 31.4% | AbN3 | unknown_sensory |
| SNxx01 | 21 | 12,079 | 28.6% | AbN4 | unknown_sensory |

SNch01 matches the connectivity signature best but is explicitly excluded by the
protocol as a wing-margin gustatory type. No candidate is an unambiguous match,
so the Milestone 5 target still needs an explicit criterion and decision.

## 8. Limits

- One run per condition, no seed replicates. These are single deterministic
  trajectories, not samples of a distribution.
- ViZDoom tints the screen on damage, so every condition, `none` included,
  receives a visual damage cue. That is what Control B measures.
- The ppk+/Gr28b.d+ heat-nociceptor identity of SNxx29 is inferred from MANC-era
  literature. MaleCNS v1.0 carries no `receptorType` for these cells and the
  MaleCNS paper does not describe them.
- The transducer from hit points to millivolts is an engineering choice. No
  value in it is physiologically calibrated.
- Simultaneous bilateral stimulation of all 20 cells is a simplification; Doom
  reports only how much damage was taken, not where.
- 600 s of neural time per condition is short. Nothing here addresses learning,
  which requires plasticity and far longer runs.

## 9. Open questions

1. Does a higher gain (40 mV-eq) or a different population reach the
   dopaminergic neurons? Without a DAN response there is no teaching signal for
   the existing plasticity rule.
2. Can the effect on ascending neurons propagate further under plasticity, or
   does it stay confined to the VNC?
3. Does preserving neural state across deaths matter at all? Protocol control E
   is not implemented yet.
4. The plasticity rule's memory decays with a 1,800 s neural time constant,
   roughly 30 simulated minutes. Long runs need that parameter examined before
   any learning claim.
