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
| H on every qubit (18 gates) | 10 ms | 45 ms | 21 ms | 8 ms | 87 ms |
| H, then a CX chain (18 gates) | 10 ms | 37 ms | 38 ms | 9 ms | 42 ms |
| H layer, then Rz on every qubit (36 gates) | 18 ms | 79 ms | 23 ms | 8 ms | 69 ms |
| random, depth 20 (540 gates) | 208 ms | 1.23 s | 308 ms | 132 ms | 847 ms |
| QFT (180 gates) | 39 ms | 167 ms | 116 ms | 52 ms | 354 ms |
| **20 qubits** | | | | | |
| H on every qubit (20 gates) | 42 ms | 205 ms | 113 ms | 31 ms | not run |
| H, then a CX chain (20 gates) | 38 ms | 111 ms | 119 ms | 57 ms | not run |
| H layer, then Rz on every qubit (40 gates) | 105 ms | 437 ms | 97 ms | 38 ms | not run |
| random, depth 20 (600 gates) | 1.01 s | 5.69 s | 1.63 s | 508 ms | not run |
| QFT (220 gates) | 185 ms | 864 ms | 473 ms | 194 ms | not run |
<!-- /table -->

Aer's time divided by `qsim` (LLVM) at 20 qubits; above 1, `qsim` is faster:

<!-- table:ratios -->
| workload | Aer 1 thread / qsim (LLVM) | Aer 4 threads / qsim (LLVM) | Cranelift / LLVM |
|---|---|---|---|
| H on every qubit | 2.71x | 0.75x | 4.9x |
| H, then a CX chain | 3.14x | 1.50x | 2.9x |
| H layer, then Rz on every qubit | 0.92x | 0.36x | 4.2x |
| random, depth 20 | 1.61x | 0.50x | 5.6x |
| QFT | 2.55x | 1.05x | 4.7x |
<!-- /table -->

The exact density matrix (`dm`), a random circuit with depolarizing noise after every gate, against Aer's
density-matrix method on one thread:

<!-- table:dm -->
| qubits | qsim `dm` (LLVM) | qsim `dm` (Cranelift) | Aer density matrix, 1 thread | qsim (LLVM) / Aer |
|---|---|---|---|---|
| 4 | 3 ms | 11 ms | 4 ms | 0.6x |
| 6 | 33 ms | 193 ms | 17 ms | 1.9x |
| 8 | 879 ms | 4.47 s | 118 ms | 7.4x |
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
5. **The density matrix is the weak spot.** At 8 qubits `dm` takes 0.88 s against Aer's 0.12 s on one thread
   (about 7 times), and 4.5 s with Cranelift. It stores the matrix as a state of twice as many qubits and
   builds each channel from Kraus operators with full-size scratch copies; a direct channel kernel would be
   much faster. The mode is capped at 10 qubits for the same reason.
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

## Not measured

Noisy sampling at scale (`qsim` runs one trajectory per run, so 1000 noisy shots are 1000 runs; one run of the
10-qubit random circuit with gate noise and 1000 samples from its state takes 0.03 s with LLVM, which is not
1000 trajectories); other machines, in particular arm64 hardware; Cirq, Qulacs or other simulators; and
the accuracy of any of these, which `check_diff.py` checks separately (amplitudes within 1e-12 of Qiskit).
