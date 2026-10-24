# Noise

> **Status: built and measured.** Compiler `3fa3fbb`, Qiskit 2.6.1. Checked by
> `scripts/check_noise.py` (physics), `check_diff.py` (each run, bit for bit),
> `check_determinism.py` and `check_types.py`. The exact counterpart is
> `density-results.md`.

## What was built

Five channels and two modelling tools, in `src/noise.cho`, in the circuit format, and
(for the channels) on the typed layer (`qubit.depol(q, st, rng, num, den)`; the qubit is
borrowed `&!` and stays a `res`). A probability is `num/den`.

| Operation | Meaning |
|---|---|
| `bitflip q p`, `phaseflip q p` | X, or Z, with probability p |
| `depol q p` | with probability p, X, Y or Z, equally likely |
| `ampdamp q g` | decay |1> to |0> with probability g * P(1); otherwise shrink |1> |
| `depol2 a b p` | with probability p, one of the 15 non-identity Pauli pairs, equally likely |
| `readout p` | every measured (`m`) or sampled (`sample`) bit is *reported* flipped with probability p; the state is not changed |
| `model1 p`, `model2 p` | a gate-noise model: depolarizing noise after every one-qubit gate (`model1`) or two-qubit gate (`model2`: CNOT, CZ, controlled phase, SWAP); `0` turns it off. Not after Toffoli, measurement or another noise operation |

**By trajectories.** The state stays a pure vector. A channel applies *one* randomly
chosen Kraus operator, with the probability the channel gives it, and renormalises. One run
is one noisy outcome, not a mixed state; the average of |psi><psi| over many runs is the
density matrix.

Every channel draws exactly one number from the sampler whether or not it fires. Readout
error draws only when its probability is above zero (one number per measured bit; per
qubit and per sample for `sample`), so a circuit without it draws exactly as before.

## Measured

1. **Each run is exact, bit for bit.** 18 noisy circuits (8 seeds of one circuit,
   probability 0 and 1, a 4-qubit chain with `sample`, 4 seeds with a gate-noise model,
   readout error and `sample`, and 3 seeds of two-qubit depolarizing) agree with a
   Qiskit-based reference that applies the same random decisions: worst amplitude error
   0 (all 65 circuits: 1.22e-15).
2. **The average is the physics.** For six noisy circuits (up to 3 qubits: all five
   channels, and the gate-noise model on a GHZ state) the mean of |psi><psi| over 4000
   seeded runs matches the density matrix computed from the Kraus operators, with every
   entry within 1.5 standard errors in the worst case (z 0.1 to 1.4), and trace distance
   below 0.012. The exact side uses `qiskit.quantum_info.Kraus` and never samples.
3. **Readout error is binomial.** With p = 1/4 on a true 1 and a true 0, 4000 seeded runs
   give z = 1.06 on the reported bits, and 4000 samples of `|1>` give z = 0.11.
4. **The test can fail.** Doubling a probability in the circuit is caught at z = 28.
5. **A Bell pair under depolarizing noise** (`docs/data/noise_curve.json`): the fidelity falls
   as 1 - p; 2000 seeded runs per point follow that line within noise (largest gap 0.9
   standard errors; p = 0 is exact and has no spread, so it is left out of that figure).
6. **Typed:** `tests/accept/noisy_bell.cho` runs 300 shots of a typed Bell pair through
   depolarizing noise (p = 1/4); the bits disagree 59 times where 1/6 of 300 = 50 is
   expected (1.4 standard deviations). A Python copy of the sampler reproduces the 59.
   `depol2` with one borrow passed twice is accepted and traps (`depol2_same_handle`).
7. **Determinism:** all 65 circuits, six builds each (three for the density-matrix ones),
   byte-identical; no earlier output hash changed, including through the readout code path
   added to the compiled circuits.

## Not done

- **Not exact.** One run does not give the mixed state; an average of many does, to within
  sampling error (about 1/sqrt(runs)). The density-matrix mode (`density-results.md`) is the
  exact version, up to 10 qubits.
- The model is one depolarizing probability for all one-qubit gates and one for all
  two-qubit gates: no per-qubit or per-gate-type rates, no noise after Toffoli, no idle noise.
- No correlated or non-Pauli two-qubit noise. `readout` is symmetric; `readerr` (see `noise-profile.md`) is
  asymmetric, per qubit.
- The z-score test is statistical. With the thresholds used a correct simulator fails it with
  probability around 1e-4 per circuit; the seeds are fixed, so the result is reproducible, but a
  different seed set could in principle cross the line.
