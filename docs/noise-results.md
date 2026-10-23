# Noise

> **Status: built and measured.** Compiler `3fa3fbb`, Qiskit 2.6.1. Checked by
> `scripts/check_noise.py` (physics), `check_diff.py` (each run, bit for bit),
> `check_determinism.py` and `check_types.py`.

## What was built

Four channels, each acting on one qubit, in `src/noise.cho`, in the circuit format
(`bitflip q num den`, `phaseflip`, `depol`, `ampdamp`; the probability is `num/den`) and
on the typed layer (`qubit.depol(q, st, rng, num, den)`; the qubit is borrowed `&!` and
stays a `res`).

**By trajectories.** The state stays a pure vector. A channel applies *one*
randomly chosen Kraus operator, with the probability the channel gives it, and
renormalises. One run is therefore one noisy outcome, not a mixed state; the
average of |psi><psi| over many runs is the density matrix.

| Channel | One run |
|---|---|
| bit flip, probability p | X with probability p |
| phase flip, probability p | Z with probability p |
| depolarizing, probability p | with probability p, X, Y or Z equally likely |
| amplitude damping, decay g | jump (|1> to |0>) with probability g * P(1), else shrink the |1> amplitudes; renormalise |

Every channel draws exactly one number from the sampler whether or not it fires, so a
channel with probability 0 does not move later draws.

## Measured

1. **Each run is exact, bit for bit.** 11 noisy circuits (8 seeds of one circuit,
   probability 0, probability 1, and a 4-qubit chain with `sample`) agree with a
   Qiskit-based reference that applies the same random decisions: worst amplitude
   error 0 (it is at most 1.22e-15 over all 45 circuits).
2. **The average is the physics.** For four noisy circuits (up to 3 qubits, all
   four channels) the mean of |psi><psi| over 4000 seeded runs matches the density
   matrix computed from the Kraus operators, with every entry within 1.5 standard
   errors in the worst case (z 0.1 to 1.4), and trace distance below 0.01. The exact side
   uses `qiskit.quantum_info.Kraus` and never samples.
3. **The test can fail.** Doubling a probability in the circuit is caught at
   z = 28.
4. **A Bell pair under depolarizing noise** (`docs/data/noise_curve.json`): the fidelity
   falls as 1 - p; 2000 seeded runs per point follow that line within noise (largest
   gap 0.9 standard errors; p = 0 is exact and has no spread, so it is left out of that figure).
5. **Typed:** `tests/accept/noisy_bell.cho` runs 300 shots of a typed Bell pair through
   depolarizing noise (p = 1/4); the bits disagree 59 times where 1/6 of 300 = 50 is
   expected (1.4 standard deviations). A Python copy of the sampler reproduces the 59.
6. **Determinism:** all 45 circuits, six builds each, are byte-identical; the output
   hashes of the 34 older circuits did not change.

## Not done

- **Not exact.** One run does not give the mixed state; an average of many does, to
  within sampling error (about 1/sqrt(runs)). A density-matrix simulator would give
  it exactly and square the memory. Not built.
- No noise attached to gates automatically: a channel is an operation you write.
- One-qubit channels only; no correlated noise, readout error, or two-qubit
  depolarizing.
- The z-score test is statistical. With the thresholds used a correct simulator fails
  it with probability around 1e-4 per circuit; the seeds are fixed, so the result is
  reproducible, but a different seed set could in principle cross the line.
