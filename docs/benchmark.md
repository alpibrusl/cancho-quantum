# Where qsim stands: a benchmark against Qiskit

> **Status: measured, one machine.** `scripts/bench_compare.py` writes `docs/data/benchmark.json`;
> `scripts/bench_report.py` fills the tables below from it (`--check` fails if they drift). Nothing
> here is a gate: timings move with the machine, which is recorded in the data file.

## What was measured

Five circuits (built once, rendered for every simulator) at 10, 14, 18 and 20 qubits:

- **H layer**: H on every qubit. Memory-bound: every gate streams the whole state.
- **CX chain**: H, then CX down the chain.
- **Rz layer**: an H layer, then Rz on every qubit (a diagonal gate).
- **random, depth 20**: seeded H/T/Ry on every qubit, then CX on random pairs, 20 times.
- **QFT**: H and controlled phases, then the swaps.

Simulators: `qsim` built by Cranelift (the default backend) and by LLVM, timed as a whole process (start,
parse, run, `quiet` so nothing is printed; start-up alone is 1.2 to 1.3 ms and is not subtracted); Qiskit
Aer 0.18's statevector method on 1 and on 4 threads, timing `run` only (the circuit is built and
transpiled first, ends in `measure_all` with one shot so the whole state is simulated and little is
copied out, and Aer's truncation of unmeasured qubits is switched off); and Qiskit's own `Statevector`
(Python and NumPy), up to 18 qubits. Each time is the minimum of 5 runs (3 at 20 qubits).

Two cautions about the setup, found by running it. First, asking Aer for the whole statevector made it look
slower than it is, because copying 16 MiB into Python is not simulation; and asking it for one qubit's
probabilities made it look absurdly fast (1 ms), because Aer then drops the qubits that cannot matter. The
`measure_all` form is the one that makes it simulate everything. Second, the compiler used here is a debug
build; that affects how long compiling takes, not the code it generates.

## Results

Times at the two largest sizes (`qsim` is the whole process; Aer is `run` only):

<!-- table:workloads -->
| workload | qsim (LLVM) | qsim (Cranelift) | Aer, 1 thread | Aer, 4 threads | Qiskit Statevector |
|---|---|---|---|---|---|
| **18 qubits** | | | | | |
| H on every qubit (18 gates) | 10 ms | 41 ms | 20 ms | 6 ms | 86 ms |
| H, then a CX chain (18 gates) | 7 ms | 23 ms | 26 ms | 14 ms | 55 ms |
| H layer, then Rz on every qubit (36 gates) | 16 ms | 71 ms | 20 ms | 7 ms | 57 ms |
| random, depth 20 (540 gates) | 189 ms | 1.04 s | 282 ms | 111 ms | 818 ms |
| QFT (180 gates) | 38 ms | 144 ms | 104 ms | 33 ms | 283 ms |
| **20 qubits** | | | | | |
| H on every qubit (20 gates) | 37 ms | 231 ms | 85 ms | 34 ms | not run |
| H, then a CX chain (20 gates) | 31 ms | 97 ms | 108 ms | 45 ms | not run |
| H layer, then Rz on every qubit (40 gates) | 69 ms | 323 ms | 83 ms | 26 ms | not run |
| random, depth 20 (600 gates) | 831 ms | 4.54 s | 1.18 s | 386 ms | not run |
| QFT (220 gates) | 180 ms | 748 ms | 467 ms | 125 ms | not run |
<!-- /table -->

Aer's time divided by `qsim` (LLVM) at 20 qubits; above 1, `qsim` is faster:

<!-- table:ratios -->
| workload | Aer 1 thread / qsim (LLVM) | Aer 4 threads / qsim (LLVM) | Cranelift / LLVM |
|---|---|---|---|
| H on every qubit | 2.28x | 0.91x | 6.2x |
| H, then a CX chain | 3.49x | 1.45x | 3.1x |
| H layer, then Rz on every qubit | 1.22x | 0.38x | 4.7x |
| random, depth 20 | 1.42x | 0.47x | 5.5x |
| QFT | 2.59x | 0.69x | 4.2x |
<!-- /table -->

The exact density matrix (`dm`), a random circuit with depolarizing noise after every gate, against Aer's
density-matrix method on one thread:

<!-- table:dm -->
| qubits | qsim `dm` (LLVM) | qsim `dm` (Cranelift) | Aer density matrix, 1 thread | qsim (LLVM) / Aer |
|---|---|---|---|---|
| 4 | 1 ms | 2 ms | 4 ms | 0.3x |
| 6 | 5 ms | 22 ms | 16 ms | 0.3x |
| 8 | 86 ms | 331 ms | 94 ms | 0.9x |
<!-- /table -->

## What it says

1. **On one core, `qsim` built with LLVM is as fast as Aer or faster** on every circuit here, from level on
   the Rz layer to about 3 times faster on the CX chain. That was not expected, and it is partly explained by
   what is not timed: Aer's time is `run` alone and `qsim`'s includes starting the process. It is
   measured, not a claim about every circuit; Aer fuses gates on larger circuits and these are not
   tuned to either simulator.
2. **With all four cores Aer is ahead on most circuits**: by 1.3 to 2.8 times on the H layer, the Rz layer and
   random circuits at 20 qubits, about level on QFT, and behind `qsim` on the CX chain. `qsim` is
   single-threaded, and a threaded gate kernel is the obvious next step; nothing in the design prevents it.
3. **The backend matters more than anything else**: Cranelift is 3 to 6 times slower than LLVM on the same
   source. A user who wants speed should build with `--backend llvm`; the default stays Cranelift because it
   compiles faster.
4. **Memory is the state and little else**: a 20-qubit run peaks at 17.3 MiB for a 16 MiB state. (Aer's
   figure in `benchmark.json`, 209.5 MiB, includes the Python interpreter and Qiskit and is not comparable.)
5. **The density matrix was the weak spot, and is now level with Aer's.** At 8 qubits `dm` took 0.88 s against Aer's 0.12 s on
   one thread (about 7 times). It stored the matrix as a state of twice as many qubits and built each channel from
   Kraus operators with full-size scratch copies: about 18 passes over the matrix per channel. Each channel is now
   a single in-place pass over the 2 x 2 (or 4 x 4) blocks it acts on, one-qubit gates and CX are one pass instead of
   two (`src/density.cho`), and the two scratch matrices are gone (a third of the memory). The table above has the
   result: 8 qubits in 0.09 s, 0.9 times Aer's time. The channels moved the amplitudes by at most 3e-15 (the sums are in
   another order; four goldens were regenerated for that); the gate fusion changed no output bit. CZ, SWAP, CP and
   CCX are still two passes. The mode is still capped at 10 qubits.
6. **Capacity**: `qsim` stops at 20 qubits (a fixed layout, 16 MiB); Aer goes well past 30 on memory it
   is given. That is a design limit here, not something the benchmark changes.

## Is it the language? The same kernels in C

The comparison above is of whole implementations. To ask what the *language* costs, `bench/kernels.c` writes the
H, CX and diagonal-gate loops of `src/gates.cho` in C, in two forms: **same loop** (visit every index, test the
qubit's bit, as `gates.cho` does) and **pairs only** (visit just the amplitude pairs, no test). They are built at
-O3 for the baseline x86-64 target (no `-march=native`, as cancho builds) with clang 18, which is LLVM like the
backend cancho's `--backend llvm` uses, and with gcc 13. Their amplitudes were first checked against `qsim`'s
(identical, to the bit, on all three workloads at 10 qubits). Whole process at 20 qubits, minimum of 5
(`scripts/bench_kernels.py`, `docs/data/benchmark_kernels.json`):

<!-- table:kernels -->
| workload | qsim (LLVM) | C, clang, same loop | C, gcc, same loop | C, clang, pairs only | C, gcc, pairs only | qsim / C, same loop | qsim / best tuned C |
|---|---|---|---|---|---|---|---|
| H on every qubit | 36 ms | 36 ms | 42 ms | 33 ms | 32 ms | 0.99x | 1.11x |
| H, then a CX chain | 39 ms | 35 ms | 36 ms | 26 ms | 33 ms | 1.09x | 1.49x |
| H layer, then Rz on every qubit | 80 ms | 61 ms | 58 ms | 53 ms | 59 ms | 1.31x | 1.49x |
<!-- /table -->

Reading it: where the algorithm is the same, cancho and C are within about 0 to 30 percent, and the
largest gap is on the diagonal gate (31 percent; why was not investigated: the complex arithmetic goes through
small functions in `complex.cho`, which the optimizer may not fully flatten). Writing the loop better in C (pairs only) is worth 10 to 35 percent on the
H layer and CX chain, because at 20 qubits all of these are limited by streaming a 16 MiB state through memory,
not by arithmetic. So the 3 to 6 times between the two cancho backends is the compiler's optimizer, not the
language, and the factor between `qsim` and Aer on four threads is parallelism, not a slow language. This is three
kernels at one size on one machine: it does not cover the noise code, the density matrix or the sampler.

## The parts added since: the OpenQASM reader, and the two variational examples

Measured by `scripts/bench_features.py` into `docs/data/bench_features.json` (the tables are filled from it by `bench_report.py`, like the rest). Same machine as above, same rules: whole processes, start-up (1.1 to 1.2 ms) included, minimum of 5 runs
(3 for the optimiser runs). One caution first: **a QASM run ends by printing every non-zero amplitude**, and the first benchmark's `quiet` exists only for `.qc` files, so a 300-gate circuit at 20 qubits took 16 s, almost all of it printing
a million lines. The tables therefore use 4 qubits for the reader itself, and a separate row per size for the printing.

**The reader** (a seeded circuit of 300 `h`, `t`, `rz`, `cx`, on 4 qubits; Qiskit's `qasm2.loads` is the reader alone, without Python's start or the import of Qiskit, so it favours Qiskit):

<!-- table:qasm -->
| program | qsim (LLVM) | qsim (Cranelift) | Qiskit `qasm2.loads` alone |
|---|---|---|---|
| 4 qubits, multiples of pi (300 gates, 3,651 bytes) | 1.9 ms | 2.8 ms | 1.0 ms |
| 4 qubits, decimal angles (300 gates, 4,483 bytes) | 2.3 ms | 2.5 ms | 0.9 ms |
| 4 qubits, every gate a call of a definition (300 gates, 4,041 bytes) | 2.9 ms | 5.2 ms | 1.7 ms |
| 8 qubits, H on every qubit (a dense state, 256 amplitudes printed) (8 gates, 89 bytes) | 6.5 ms | 13.4 ms | n/a |
| 10 qubits, H on every qubit (a dense state, 1,024 amplitudes printed) (10 gates, 106 bytes) | 18.1 ms | 48.6 ms | n/a |
| 12 qubits, H on every qubit (a dense state, 4,096 amplitudes printed) (12 gates, 124 bytes) | 79.6 ms | 193 ms | n/a |
| 14 qubits, H on every qubit (a dense state, 16,384 amplitudes printed) (14 gates, 142 bytes) | 288 ms | 678 ms | n/a |
<!-- /table -->

* **Reading is cheap and the three spellings cost about the same**: 1.9 ms for multiples of pi, 2.3 ms with decimal angles, 2.9 ms with every gate a call of a definition, of which 1.1 to 1.2 ms is the process start. Differences of a few tenths of a millisecond are inside the noise of a minimum of 5.
* **The printing is the cost at size**: about 17 microseconds per amplitude with LLVM (288 ms for the 16,384 of a dense 14-qubit state) and about 41 with Cranelift, so a dense 20-qubit state would print for about 18 seconds. The cause is not examined (the shortest-round-trip formatting of two floats per line is the obvious suspect), and it is not fixed; a flag that prints nothing, or only the non-negligible amplitudes, would remove it.

**One call of a defined gate** (4 qubits, so that no simulation is in the way; a two-gate definition `g(t) a,b { rz(t*2+0.1) a; cx a,b; }` called N times against its 2N gates written out):

<!-- table:expansion -->
| calls | defined, LLVM | written out, LLVM | per call, LLVM | defined, Cranelift | written out, Cranelift | per call, Cranelift |
|---|---|---|---|---|---|---|
| 1,000 | 3.2 ms | 1.5 ms | 1.7 us | 6.3 ms | 2.3 ms | 4.0 us |
| 10,000 | 16.2 ms | 4.6 ms | 1.2 us | 50.0 ms | 11.0 ms | 3.9 us |
| 100,000 | 211 ms | 46.6 ms | 1.6 us | 402 ms | 71.0 ms | 3.3 us |
<!-- /table -->

* **A call costs 1.2 to 1.7 microseconds with LLVM** (3.3 to 4.0 with Cranelift): the copy of the body with its names replaced, the printing and re-reading of the angle, and the two gates' own parse. 100,000 calls take 0.21 s against 0.047 s written out.
* **The budget is refused quickly**: a chain of seven definitions that call the one before ten times each (10^7 calls) is refused at the limit of 200,000 calls in 78 ms with LLVM (257 ms with Cranelift).

**The variational examples** with cancho-opt as the optimiser (`opt` and the objective programs built with LLVM; the objective is a program that `opt` starts for every evaluation, at the process start of about 1.2 ms; scipy's BFGS runs a straightforward numpy
implementation of the same circuit, whose cost was first checked against the tool's to 1e-10, with the same start, the same parameter-shift rule and a gradient tolerance of 1e-6):

<!-- table:variational -->
| run | cancho (qsim + `opt`, LLVM) | scipy BFGS on numpy, same start and gradient rule | scipy / cancho |
|---|---|---|---|
| VQE, 3 layers, BFGS with the exact gradient (56 gradients) | 110 ms | 614 ms | 5.6x |
| VQE, 3 layers, SPSA 800 iterations, exact energy (1601 evaluations) | 2.31 s | | |
| VQE, 3 layers, SPSA 800 iterations, 1,000 shots per basis (3,202,000 shots) | 2.78 s | | |
| QAOA, 1 layer, BFGS, 6 starts (73 gradients) | 117 ms | 1.13 s | 9.6x |
| QAOA, 2 layers, BFGS, 6 starts (146 gradients) | 272 ms | 3.22 s | 11.8x |
| QAOA, 3 layers, BFGS, 6 starts (254 gradients) | 607 ms | 6.32 s | 10.4x |
| QAOA, 4 layers, BFGS, 6 starts (361 gradients) | 1.04 s | 9.96 s | 9.5x |
| QAOA, 2 layers, SPSA 200 iterations, 6 starts, 1,000 shots (2,406,000 shots) | 3.66 s | | |
<!-- /table -->

* **Against scipy and numpy cancho is 5 to 12 times faster here**, but this is a comparison of a compiled simulator against a loop of small numpy calls, and the numpy side is mine and not tuned: it says that the example is fast enough to be interactive (0.1 s for the VQE, 0.1 to 1 s for QAOA), not that a tuned numpy implementation could not match it.
* **The SPSA runs are slow because of the evaluations, not the optimiser**: 1,601 evaluations in 2.3 s is 1.4 ms each, the process start of the objective. SPSA itself is 2 evaluations per iteration whatever the number of angles; that is what it saves in shots (`examples/vqe/README.md`), and it costs time when each evaluation is a process.
* One machine, one run of each (a minimum of 3), an unoptimised numpy side; nothing here is a gate.

## Not measured

Noisy sampling at scale (`qsim` runs one trajectory per run, so 1000 noisy shots are 1000 runs; one run of the
10-qubit random circuit with gate noise and 1000 samples from its state takes 0.03 s with LLVM, which is not
1000 trajectories); other machines, in particular arm64 hardware; Cirq, Qulacs or other simulators; and
the accuracy of any of these, which `check_diff.py` checks separately (amplitudes within 1e-12 of Qiskit).
