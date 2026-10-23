# M3 results: determinism and provenance

> **Status: M3 gate met on x86-64, and on aarch64 under emulation.**
> Compiler `3fa3fbb`, x86-64 Linux host, `qemu-aarch64` 8.2.2 for the second
> architecture. Everything below is produced by
> `python3 scripts/check_determinism.py --arm64`.

## The gate

> Same circuit + same seed gives byte-identical output on Cranelift and
> LLVM backends. Identical output across both backends and across two
> machines (x86-64 and arm64 if available).

**Met for backends; the "two machines" half is met only as emulation.**

For each of the 25 circuits in `tests/diff/`, six builds ran it, and all
six outputs are byte-identical (SHA-256 equal):

| | Cranelift x86-64 | LLVM x86-64 | LLVM aarch64 (qemu) |
|---|:-:|:-:|:-:|
| `qsim`, circuit interpreted from stdin | yes | yes | yes |
| circuit compiled as a cancho function | yes | yes | yes |

The hashes are checked in (`tests/golden/outputs.sha256`) and the script
fails on any change; with one hash tampered, it reports that circuit and
passes the other.

**What the arm64 result is and is not.** It is the aarch64 code LLVM
generated, run on `qemu-user`. That tests the compiler's output (including
whether any fused multiply-add changed a result: none did, on these
circuits) and the program's use of its own `sin`/`cos`. It is not arm64 *hardware*, and
the repository's `llvm-backend.md` records that real aarch64 hosts
differ from x86-64 on at least one point (the sign of `0.0 / 0.0`). This
program never produces a NaN, so that difference is not exercised here. A
run on real arm64 hardware, or macOS arm64, is still owed; the script
works there unchanged without `--arm64`.

Cranelift cannot target aarch64 (`--target` needs `--backend llvm`), so
Cranelift/aarch64 does not exist to be tested.

## Provenance

`cancho ids` gives each function a `SigId` and a `BodyId`, and a body
refers to its callees by `SigId` only (`canonical-ast.md` §2). So a
circuit's `BodyId` identifies *the circuit*, not the gates it calls. A
run record therefore has three parts, written to
`tests/golden/provenance.json`:

| field | what it covers |
|---|---|
| `circuit_body_id` | `body circuit` from `cancho ids` on the compiled circuit (`tests/circuits/<name>.cho`, generated from the `.qc`) |
| `library_digest` | SHA-256 of every library function's `BodyId`, sorted: the simulator that ran it |
| `input_sha256`, `output_sha256` | the `.qc` text and the bytes printed |

Measured: all 25 circuits have distinct `circuit_body_id`s, `cancho ids` is
stable across repeated runs, and the library digest is one value for the
set. Circuits that differ only in the seed (`measure_seed2` and
`measure_seed3` print identical output!) still have different ids, which
is the point of identifying the program and not its output.

This is a *record*, not an attestation: nothing signs it, and it proves
nothing about the machine. It does let two parties compare "same code,
same circuit, same bytes" by comparing three hashes.

## What was built

- `scripts/qc_to_cho.py`: each `.qc` becomes a compiled circuit
  (`tests/circuits/*.cho`, generated, formatted). This also turned the
  interpreter and the compiled path into a differential test of each
  other: a bug in `qsim`'s token parser would show as a mismatch.
- `src/dump.cho`: the output records, extracted from `main.cho` so the
  interpreter and compiled circuits print through the same code. The
  extraction was a pure move: all 25 outputs were byte-identical before
  and after, and the M1 and M2 gates still pass.
- `scripts/check_determinism.py`: the gate.
- `gates.angle(num, den)`: moved out of `main.cho`; one definition.

## Findings

- **Building for aarch64 works with a `cc` shim.** `cancho build
  --backend llvm --target aarch64-unknown-linux-gnu` produces an object;
  linking uses the host `cc`, so the script puts a symlink named `cc` to
  `aarch64-linux-gnu-gcc` first on `PATH`. The compiler prints a note that
  "the compiler in cancho could not build this (`clang` ... invalid
  instruction mnemonic 'udf')" and builds it with the Rust compiler
  instead: this container's `clang` lacks the aarch64 target. The output
  is correct either way; the note is worth a look in the compiler repo.
- **A circuit's hash does not move when a gate's body does.** By design
  (`SigId` indirection), and the reason `library_digest` exists. Anyone
  attesting a run with only the circuit id would miss a changed simulator.
- **Compiled circuits are long straight-line functions** (up to 160 gates
  in `random12`) and compile without trouble on both backends.

## Not done

- Real arm64 hardware, and macOS (a different libm story).
- Signing or attesting the provenance record.
- A circuit larger than 20 qubits, or any measurement-heavy workload
  beyond what `tests/diff/` holds.
- Determinism of anything that reads a clock, a file or the network: the
  program has no such capability, which `cancho authority` confirms.
