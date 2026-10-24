# Idle noise: T1 and T2

A qubit that waits decays. `qsim` models it with two numbers per qubit and a
duration.

## Operations

| op | meaning |
|---|---|
| `coher q T1 T2` | qubit `q` has relaxation time T1 and dephasing time T2, in nanoseconds. Refused (exit 2) unless 0 < T1, 0 < T2 and T2 <= 2 T1 (the physical limit). |
| `wait q ns` | qubit `q` idles for `ns` nanoseconds. Does nothing, and draws nothing from the sampler, if `q` has no `coher`. |
| `time1 ns`, `time2 ns` | a one-qubit and a two-qubit gate take `ns` nanoseconds. After each gate (and after its depolarizing noise, if any) each qubit the gate touched idles for that long. |
| `dur1 q ns`, `dur2 a b ns` | one qubit's, or one pair's (either order), own gate time, replacing `time1` / `time2` for it. Added for real-device profiles, where `cx` times differ several-fold between pairs (`calibration.md`). |

| `sched` | start every gate as soon as its qubits are free (ASAP); see below. |
| `barrier` | every qubit idles until the last one is free. |

Works in `n` mode (trajectories) and `dm` mode (exact). Not in OpenQASM input.

## Scheduling

Without `sched`, only a gate's own duration decays its qubits. With it, each qubit
has a clock (nanoseconds). A two-qubit gate starts when both of its qubits are free;
the one that was free earlier idles for the difference first (relax, then the gate,
its depolarizing noise, and its duration). A one-qubit gate starts when its qubit is
free, so it needs no wait. `wait` advances the clock. Idling is applied just before the
gate that ends it, which is the same state as idling all along, because a channel on
one qubit commutes with gates on others. A `barrier`, a `sample` and the end of the
circuit (the amplitudes or the matrix printed, `purity`, `probs`) idle every qubit to
the end of the longest one. Measurement `m`, noise operations and Toffoli take no time.

## The channel

Waiting `t` is amplitude damping with gamma = 1 - exp(-t/T1), then a phase flip
with probability (1 - exp(-t * r)) / 2, where r = 1/T2 - 1/(2 T1) is the pure
dephasing rate (0 when T2 = 2 T1). The two commute. The population of |1> decays
as exp(-t/T1) and the off-diagonal element of a superposition as exp(-t/T2),
which is what T1 and T2 mean. `exp` is `std.math.exp` (fdlibm ported to cancho),
so it is the same on every build.

In `n` mode the trajectory draws exactly twice per `wait` on a qubit that has a
`coher` (damping, then the flip), and not at all otherwise, so adding a `wait`
on a qubit without `coher` moves no later draw.

## What was measured

- `scripts/idle_curve.py`: T1 = 50 us, T2 = 70 us, waiting 0 to 100 us. The
  density-matrix population and coherence agree with exp(-t/T1), exp(-t/T2)/2
  **and with Qiskit Aer's `thermal_relaxation_error`** to 1.2e-15
  (`docs/data/idle_curve.json`).
- 10 new circuits in `tests/diff` (6 `dm_idle_*` against Aer on the density
  matrix, including T2 = 2 T1 and T2 < T1; 4 `idle_seed*` trajectory circuits
  against a Python reference that mirrors the draw order). Worst amplitude error
  over all 80 circuits: 9.7e-15.
- `scripts/check_noise.py`: a 3-qubit GHZ circuit with three different T1/T2,
  gate times of 3.5 us and 30 us and two waits, 4000 runs against the exact
  density matrix: max z 3.06 over about 128 matrix entries. At 16000 runs max z
  fell to 1.64 and the trace distance from 0.0126 to 0.0054 (about 1/sqrt(N)),
  so it is sampling noise, not bias.
- 4 trap fixtures (T2 > 2 T1, T1 = 0, qubit past n, negative gate time).
- Output hashes of the 70 earlier circuits did not change.

## Not modelled

- **ASAP only.** `sched` is as-soon-as-possible with no gate reordering, no dynamical
  decoupling and no ALAP; a mid-circuit `m` takes no time and does not synchronise.
- Toffoli has no duration (it is not a native gate), as it has no gate noise.
- Gate duration is per qubit (one-qubit gates) and per pair (two-qubit gates), not per gate type: every one-qubit gate takes the same time.
- Thermal excitation (a nonzero-temperature T1 channel) is not modelled; the
  qubit relaxes towards |0> only.

## Scheduling: what was measured

`scripts/check_schedule.py`: 6 random 14-gate circuits on 4 qubits (different T1, T2 per
qubit, a pair and a qubit with their own gate times), with start times from Qiskit's
`ASAPScheduleAnalysis` and decay from Aer's channel on Qiskit's DensityMatrix, against
`qsim`'s density matrix under `sched`: trace distance 1.6e-15 to 8.6e-15. Without `sched`
the same circuits are 6e-3 to 6e-2 away. A qubit left as |1> while a chain of `cx` runs
elsewhere follows exp(-t/T1) to 2e-16 (`docs/data/schedule_curve.json`). 6 `dm_sched_*` /
`sched_seed*` circuits in `tests/diff` pass against the Python reference (worst amplitude error
over 86 circuits 1.2e-14), and a sampled 3-qubit scheduled circuit matches the exact density matrix
within statistics (`check_noise.py`).
