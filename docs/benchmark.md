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
| H on every qubit (18 gates) | 9 ms | 41 ms | 18 ms | 7 ms | 97 ms |
| H, then a CX chain (18 gates) | 9 ms | 22 ms | 26 ms | 14 ms | 64 ms |
| H layer, then Rz on every qubit (36 gates) | 17 ms | 71 ms | 20 ms | 7 ms | 57 ms |
| random, depth 20 (540 gates) | 194 ms | 997 ms | 273 ms | 93 ms | 784 ms |
| QFT (180 gates) | 36 ms | 147 ms | 104 ms | 33 ms | 275 ms |
| **20 qubits** | | | | | |
| H on every qubit (20 gates) | 43 ms | 228 ms | 83 ms | 25 ms | not run |
| H, then a CX chain (20 gates) | 36 ms | 98 ms | 112 ms | 43 ms | not run |
| H layer, then Rz on every qubit (40 gates) | 66 ms | 307 ms | 88 ms | 25 ms | not run |
| random, depth 20 (600 gates) | 896 ms | 4.55 s | 1.20 s | 416 ms | not run |
| QFT (220 gates) | 187 ms | 786 ms | 487 ms | 162 ms | not run |
<!-- /table -->

Aer's time divided by `qsim` (LLVM) at 20 qubits; above 1, `qsim` is faster:

<!-- table:ratios -->
| workload | Aer 1 thread / qsim (LLVM) | Aer 4 threads / qsim (LLVM) | Cranelift / LLVM |
|---|---|---|---|
| H on every qubit | 1.93x | 0.57x | 5.3x |
| H, then a CX chain | 3.10x | 1.20x | 2.7x |
| H layer, then Rz on every qubit | 1.32x | 0.37x | 4.6x |
| random, depth 20 | 1.34x | 0.46x | 5.1x |
| QFT | 2.61x | 0.87x | 4.2x |
<!-- /table -->

The exact density matrix (`dm`), a random circuit with depolarizing noise after every gate, against Aer's
density-matrix method on one thread:

<!-- table:dm -->
| qubits | qsim `dm` (LLVM) | qsim `dm` (Cranelift) | Aer density matrix, 1 thread | qsim (LLVM) / Aer |
|---|---|---|---|---|
| 4 | 1 ms | 2 ms | 4 ms | 0.3x |
| 6 | 5 ms | 20 ms | 17 ms | 0.3x |
| 8 | 107 ms | 384 ms | 90 ms | 1.2x |
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
5. **The density matrix was the weak spot, and is now close.** At 8 qubits `dm` took 0.88 s against Aer's 0.12 s on
   one thread (about 7 times). It stored the matrix as a state of twice as many qubits and built each channel from
   Kraus operators with full-size scratch copies: about 18 passes over the matrix per channel. Each channel is now
   a single in-place pass over the 2 x 2 (or 4 x 4) blocks it acts on (`src/density.cho`), the two scratch matrices
   are gone (a third of the memory), and the table above has the result: 8 qubits in 0.11 s, 1.2 times Aer's time. Gates are
   still two passes each (rows, then columns), which is where the remaining gap is. The amplitudes moved by at most
   3e-15 (the sums are in another order); four goldens were regenerated for that. The mode is still capped at 10 qubits.
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
