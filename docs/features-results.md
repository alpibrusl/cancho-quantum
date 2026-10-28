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
  circuits with `qasm2.dumps`: **18 ran and 2 were refused** because Qiskit wrote a
  decimal angle (for example `-399.8243433872783` for -12345 pi / 97); **since the decimal reader (below) all 20 run**, the `rz_sweep` file with its angles of up to 3 million radians among them.

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
- **A decimal angle can be read bit for bit, but it took a division with the rounding done by hand.** This document used to say it could not, and that
  cancho's `std` has no correctly rounded decimal parser; the reader now has one for the range an angle uses (`src/qasm.cho`, `number`). Dividing the double of the digits by the double of a
  power of ten rounds twice and is wrong in the last place for about 1 text in 17 of those checked once the digits exceed 2^53 (17-digit angles, which Qiskit writes): the reader long-divides the digits to 54 bits
  and rounds once, to nearest even. `scripts/check_qasm.py` compares it with Python's `float` on 18,252 texts (random doubles' `repr`, random digit strings of 1 to 18 digits with
  a point and an exponent, and exact halfway cases): bit for bit when the digits (at most 18) are a power of ten of at most 18 below, 22 either way below 2^53 digits, or times the power below 2^62, and within 2 ulp
  outside it (huge or tiny angles). With the division done in doubles the same check finds 1,081 wrong. A multiple of pi (`3*pi/4`) is still `pi * num / den`, the double the references compute.
- **One character of lookahead cannot tell a comment from division.** `//` and
  `pi/4` both start with `/`; the QASM reader handles comments only at the start
  of a statement. Qiskit writes none, and the reader says so in a comment.
- **Two new refusals worked first time.** SWAP with the same qubit through
  two borrows is `borrow-conflict`; a Toffoli whose control is borrowed shared and
  used where a unique borrow is needed is `type-mismatch`. Passing one borrow twice
  is accepted (the same gap as CNOT).

## Not done

- No noise and no density matrices; the state is pure.
- QASM: no `gate` definitions, no `cu3`/`rxx`/`csx`, and one `qreg` only. Read since: decimal angles, `u3`/`u2`, `cy`/`ch`/`crz`/`rzz`/`cswap` (120 random circuits against Qiskit to 1e-12), up to four `creg`s, `measure q[i] -> c[j]` and `if (c==k)` (120 programs whose outcomes are certain, against Aer's final state; a flipped condition and a `measure` that sets the wrong bit are each caught).
  QASM is not written by cancho yet (a Python script writes it).
- `sample` is at most 4096 draws, each costing one pass over the state; a
  billion-amplitude register is out of range anyway (the limit is 20 qubits).
- Speed of the new gates was not measured (the timing graph on the page is for H).
- Still one reference implementation: Cirq is not used.
- The authority capability (M4): the compiler has none (`cancho#612` tracks its design); a first slice of its semantics is a library, `src/qpu.cho`, with its limits stated in `docs/qpu.md` (no check-time refusal, no `limit` in `cancho authority`).
