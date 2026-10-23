# M1 results: the simulator without types

> **Status: M1 gate met.** Compiler `3fa3fbb` (alpibrusl/cancho), Qiskit
> 2.6.1, numpy 2.5.3, x86-64 Linux. Every number below was produced by
> `python3 scripts/check_diff.py` and is reproducible with it; claims not
> measured say so.

## What was built

| File | Contents |
|---|---|
| `src/complex.cho` | `Complex` as a two-float `val struct`; add, sub, mul, scale, norm |
| `src/state.cho` | state vector layout: interleaved re/im, little-endian qubit order |
| `src/gates.cho` | H, X, Z, S, T, RZ, CNOT, CZ on plain `int` qubit indices |
| `src/measure.cho` | xorshift64* sampler, measurement with collapse |
| `src/main.cho` | `qsim`: reads a circuit on stdin, prints amplitudes |
| `scripts/gen_reference.py` | generates the circuits and Qiskit references |
| `scripts/check_diff.py` | builds `qsim`, runs every circuit, gates the diff |

The state lives in a zero-filled `Box[[float]]` (a `calloc`), so `n = 20`
(16 MiB) works. The circuit format is documented at the top of
`src/main.cho`.

## The gate

> Statevector matches Qiskit/Cirq reference to a stated tolerance
> (e.g. 1e-12) on a fixed set of circuits. Record the ulp error of
> `sin`/`cos` use in RZ.

- **25 circuits** in `tests/diff/`: Bell; GHZ(3..10) and GHZ(20); every
  gate once; random circuits on 5, 8 and 12 qubits (60 to 160 gates);
  an RZ sweep over 40 angles up to `pi * 999983 / 1`; a `sin`/`cos`
  isolation set; and nine circuits with measurement.
- **Worst amplitude error: 1.22e-15** (absolute, real or imaginary part),
  against a gate of 1e-12. It is on `measure_random6`. GHZ and Bell are
  exact (0).
- **`sin`/`cos`: at most 1 ulp from the C library** over 77 angle pairs,
  half-angles from 0.016 to 6.3e6. The upper end is past the `10^6` where
  `float-math.md` §8's fast reduction stops and Payne–Hanek takes over,
  so both reductions are covered. RZ's contribution to the amplitude
  error is within the 4.6e-16 of `rz_sweep`.
- **The check can fail.** `--tol 0` fails 11 of 25 circuits. Changing one
  `t` to `s` in `random5.qc` fails it at error 1.9e-1.
- **Measurement is checked against an independent implementation**
  (`gen_reference.py` carries its own xorshift64* and projects Qiskit's
  state with numpy). All nine measurement circuits agree on every bit
  and on the collapsed state. Six seeds of one circuit give six
  different outcomes, so the seed is doing something.
- **Five programs must stop** (`tests/trap/`): CNOT or CZ on one qubit
  twice, a qubit index past `n`, a negative index, and `n > 20`. All
  exit non-zero and print no amplitudes.

## What was measured besides the gate

**Both backends agree to the byte, on this machine.** All 25 circuits'
outputs are byte-identical between `--backend cranelift` and
`--backend llvm`. That is a preview of M3, not M3: one machine, and
x86-64 only. It does bear on idea-doc risk R4 (fused multiply-add): on
x86-64, neither backend differed. It says nothing about arm64.

**Cost of `Complex` as a struct** (20 H gates on 20 qubits, 2^20
amplitudes, output suppressed with `quiet`; one run each, not a
benchmark):

| backend | `Complex` struct | raw floats | ratio |
|---|---:|---:|---:|
| Cranelift | 0.246 s | 0.121 s | 2.0x |
| LLVM | 0.069 s | 0.062 s | 1.1x |

Cranelift pays about 2x for passing a two-float struct by value on this
loop; LLVM pays about 10%. GHZ(20) (20 gates, two non-zero amplitudes)
runs in 0.27 s (Cranelift) and 0.21 s (LLVM). Within the PoC's `n <= 20`
target, the struct is affordable.

**Printing, not simulating, is the slow part.** The same 20-H circuit
with all 1,048,576 amplitudes printed takes 52 s (Cranelift) and 24 s
(LLVM), against 0.25 s and 0.07 s with output off. That is
`std.fmt.float_into` at roughly 12 to 25 microseconds per float on values
that have no short decimal form. It does not bear on correctness, but
anything that dumps a large state should print a hash or the non-zero
entries.

**`cancho authority` already says something.** For the whole program it
reports `heap`, `io_read`, `io_write` and nothing else, and "never
touches: the filesystem, the network, the command line, signals, other
programs, foreign code". That is the property M4 wants for a `Qpu`
capability, and it is free here because the simulator is pure
computation.

## Answers to the questions M0 left for M1

1. **Can a boxed zero-initialised state be written through `&!`?** Yes.
   `borrow mut b as &!w in { let st = contents(w); st[i] = ... }` gives a
   writable slice (`tests/accept/boxed_slice.cho` says the same). A shared
   borrow gives a read-only one. Wording in `qubit-types.md` §8 that this
   was open is corrected there.
2. **Does the runtime check close reject #4?** For the simulator as a
   program, yes: `cx 1 1` traps (`tests/trap/cx_same_qubit.qc`). That is
   a trap, not a refusal, as `qubit-types.md` §4.2 said it would be. M2
   decides whether the typed layer needs more.

## Findings that change M2's plan

- **`cancho fmt` cannot reproduce `import ... as`.** Formatting fails on
  a file that uses it ("`as` has no counterpart in the canonical
  rendering"), so imports use the module's last segment. This is a
  compiler-side nit, not a cancho-quantum problem; recorded here, not
  filed.
- **A function and an import cannot share a short name.** `gates.t` and a
  parameter `t` collide in a reader's head, and `measure.measure` reads
  badly. Cosmetic, but M2's `Qubit` API will want distinct names for the
  module and its main function.
- **The compiler's diagnostics were enough to write M1.** The only
  refusals met were: `std.test.assert(...)` is not
  a valid qualified call (use the import's last segment), and `std.math`
  needs its own `import`. Each was named by the message. (A missing
  `[&s]` on two helpers was fixed before the first `check`, so it is not
  counted.)

## Not done

- Cirq was not used; Qiskit was enough for the stated gate.
- `qasm.cho` (the OpenQASM emitter in the idea doc's layout) is not
  started; the circuit format here is a stand-in.
- No arm64, no second machine, no `cancho ids` hashes of circuits (M3).
- Timings are single runs on one machine and are indicative only.
