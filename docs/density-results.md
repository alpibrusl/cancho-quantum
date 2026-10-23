# Exact noise: the density matrix

> **Status: built and measured.** Compiler `3fa3fbb`, Qiskit 2.6.1. Checked by
> `scripts/check_diff.py` (10 `dm_*` circuits), `check_determinism.py` and
> `scripts/purity_curve.py`.

## What was built

A header `dm <n>` in place of `n <count>` runs the circuit on the density matrix:
`src/density.cho`. One run is the exact answer, not a sample. `purity` (Tr rho^2),
`trace` and `probs` print properties of the matrix; the matrix itself is printed as
`rho <row> <col> <re> <im>` for every entry that is not exactly zero.

**The trick, and the limit it sets.** The matrix rho (2^n by 2^n) is stored as a state
vector of 2n qubits: entry rho[i][j] is the amplitude at index `i + j * 2^n`. A gate
acts on the rows as itself (qubit q) and on the columns as its complex conjugate (qubit
q + n), so every gate in `gates.cho` runs unchanged, on 2n qubits. A channel applies
rho -> sum_k K rho K^dagger, one Kraus operator at a time into a scratch matrix. Because
the vector is limited to 20 qubits, the density matrix is limited to **10**.

Operations in this mode: every gate (17), the four channels, seeded measurement with
collapse (`m`), `seed`, `purity`, `trace`, `probs`, `quiet`. Not in this mode:
`sample`, OpenQASM, compiled circuits.

## Measured

- **Exact against Qiskit's `DensityMatrix`.** 10 circuits (every gate; all four
  channels on 3 qubits; amplitude damping; a noisy 3-qubit Fourier transform; a
  noisy 4-qubit GHZ chain; a 40-operation random circuit; probability 0 and 1;
  a measurement in the middle) agree entry by entry, worst error **5.6e-16**.
- **A formula, not just a reference.** A Bell pair through depolarizing noise on one
  qubit has purity (1 - p)^2 + p^2/3. For p = 0 to 0.5 in steps of 0.05, cancho's
  `purity`, Qiskit's and the formula agree to **7.8e-16** (`docs/data/purity_curve.json`).
- **It is the limit of the sampled method.** `noise-results.md` checks the trajectory
  method against an exact Kraus calculation in numpy; this mode is a second, independent
  exact calculation, in cancho, and it matches the same reference.
- **Determinism.** The 10 circuits run interpreted on Cranelift, LLVM and aarch64
  (under emulation) with identical bytes. They have no compiled form, so they get three
  builds, not six. No earlier hash changed.

## Not done

- No more than 10 qubits; the matrix is 16 bytes times 4^n, 16 MiB at 10 qubits, and there are two scratch matrices of the same size.
- No `sample` in this mode (it would sample from the diagonal); no OpenQASM; no
  compiled form.
- Measurement collapses the matrix to one outcome, as a run would; there is no
  "average over outcomes" operation.
- Noise is still an operation you write; there is no automatic noise per gate.
- Speed was not measured.
