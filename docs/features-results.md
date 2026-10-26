# Features after M3: gates, sampling, OpenQASM, algorithms

> **Status: built and measured.** Compiler `3fa3fbb`, Qiskit 2.6.1, x86-64 plus
> `qemu-user` aarch64. Everything below is checked by `scripts/check_diff.py`,
> `check_types.py`, `check_qasm.py` and `check_determinism.py`. No compiler
> change was made or needed.

## What was added

| Feature | Where | Checked against |
|---|---|---|
| Gates: Y, S-dagger, T-dagger, RX, RY, P (phase), controlled phase (CP), SWAP, Toffoli (CCX) | `src/gates.cho`, `src/qubit.cho` (typed) | Qiskit statevectors, 1e-12 |
| `sample N`: draw N outcomes from the whole state without collapsing it | `src/measure.cho`, `src/dump.cho` | an independent sampler (cumulative sum and binary search), counts exact |
| OpenQASM 2.0 input (a file starting `OPENQASM`) | `src/qasm.cho` | Qiskit's parser, both directions |
| Algorithms as circuits: QFT (4 qubits), Grover (3), Bernstein-Vazirani (4+1), Deutsch-Jozsa (3+1) | `tests/diff/*.qc` | Qiskit; the algorithms' known answers |
| Typed Toffoli and Bernstein-Vazirani, two new refusals, two new pinned gaps | `tests/accept`, `tests/reject` | `check_types.py`, 22 of 22 |

## Measured

- **34 circuits** now match Qiskit, worst amplitude error **1.22e-15** (unchanged:
  the new circuits are at most 3.3e-16). The 26 earlier circuits' output hashes in
  `tests/golden/outputs.sha256` did not change when the gates, the QASM reader and
  `sample` were added: those lines are byte-identical to before.
- **All 34 run six ways** (interpreted and compiled; Cranelift and LLVM; aarch64
  under emulation) with identical bytes, as before. The aarch64 half is still emulation.
- **The algorithms give their answers.** Grover finds the marked item 101 in
  951 of 1000 samples (about 0.95 is what two rounds on 8 items should give);
  Bernstein-Vazirani returns the secret `1011` in the data qubits on every
  sample; Deutsch-Jozsa returns the parity mask `101` and never all-zero (the
  balanced answer); the typed Bernstein-Vazirani reads secret 5 in 20 of 20 shots.
- **`sample` matches an independent implementation exactly**: the reference
  draws from the same generator but locates each outcome with
  `numpy.cumsum` and `searchsorted` on Qiskit's probabilities, not by adding
  one state at a time. All four sampling circuits (Grover, BV, DJ,
  `ghz5_sample`) agree count for count. A tie-break at a probability
  boundary could in principle differ by one ulp; none did.
- **OpenQASM.** All 20 circuits QASM can express (those without `seed`,
  `sample` or `trig`) are written by `tools/qcconv.cho` (cancho; `scripts/qc_to_qasm.py` is its Python reference); Qiskit's own
  reader and `qsim` agree on each. In the other direction Qiskit wrote the same
  circuits with `qasm2.dumps`: **18 run, 2 were refused** because Qiskit wrote a
  decimal angle (for example `-399.8243433872783` for -12345 pi / 97).

## Findings

- **Qiskit refuses `ccx(0, 0, 1)` when the circuit is built**
  (`CircuitError: duplicate bit arguments`). cancho-quantum's typed layer
  does not refuse it at check time, and traps at run time instead
  (`tests/accept/ccx_same_handle.cho`, `swap_same_handle.cho`). So the gap of
  `m2-results.md` entry 4 is wider in cancho-quantum than in the library it is
  compared with: Qiskit has the check, at a different time.
- **`qelib1.inc` does not define `p`, `cp` or `swap`.** Qiskit's loader rejects them in
  a file that includes it; Qiskit writes them anyway. `qc_to_qasm.py` therefore
  writes `u1`, `cu1` and three `cx` (standard QASM), and `qsim` reads both
  spellings.
- **A decimal angle cannot be read bit for bit.** The digits are rounded; a
  multiple of pi is not. The reader refuses decimals with a message instead of
  accepting an approximation that would break the references. If decimals are wanted,
  the right fix is a correctly-rounded decimal parser, which cancho's `std` does
  not have.
- **One character of lookahead cannot tell a comment from division.** `//` and
  `pi/4` both start with `/`; the QASM reader handles comments only at the start
  of a statement. Qiskit writes none, and the reader says so in a comment.
- **Two new refusals worked first time.** SWAP with the same qubit through
  two borrows is `borrow-conflict`; a Toffoli whose control is borrowed shared and
  used where a unique borrow is needed is `type-mismatch`. Passing one borrow twice
  is accepted (the same gap as CNOT).

## Not done

- No noise and no density matrices; the state is pure.
- QASM: no decimal angles, `gate` definitions, `u3`/`u2`, `if`, or more than one `qreg`.
  QASM is not written by cancho yet (a Python script writes it).
- `sample` is at most 4096 draws, each costing one pass over the state; a
  billion-amplitude register is out of range anyway (the limit is 20 qubits).
- Speed of the new gates was not measured (the timing graph on the page is for H).
- Still one reference implementation: Cirq is not used.
- The authority capability (M4): the compiler has none (`cancho#612` tracks its design); a first slice of its semantics is a library, `src/qpu.cho`, with its limits stated in `docs/qpu.md` (no check-time refusal, no `limit` in `cancho authority`).
