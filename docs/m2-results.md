# M2 results: the linear qubit layer

> **Status: M2 gate met, and the prediction in `qubit-types.md` §4 held.**
> Compiler `3fa3fbb`. Everything below is run by
> `python3 scripts/check_types.py` (16 fixtures, both backends). No
> compiler change was needed or made.

## What was built

`src/qubit.cho`: `res struct Qubit { idx, n }` with H, X, Z, S, T, RZ as
`&!` borrows, CNOT/CZ as (`&` control, `&!` target), and `measure` taking
the qubit by value. The state vector is still threaded as a `&!s [float]`.
It is a thin layer over the M1 gates; the M1 diff against Qiskit still
passes unchanged.

Two programs use it end to end:

- `tests/accept/bell.cho`: 200 shots of a Bell pair. The bits agree on
  every shot; the count of ones (92) is reproduced by an independent
  Python copy of the sampler.
- `tests/accept/teleport.cho`: teleportation of 80 different states, with
  the classically controlled X and Z corrections branching on the
  `val` bits `measure` returns. Verifying qubit 2 by undoing the
  preparation and measuring gives 0 on every shot, across all four
  outcome pairs. Removing the Z correction makes 42 of 80 shots fail, so
  the check is not vacuous.

## The gate: the five must-reject entries

| # | Error | Result | Rule tag | Fixture |
|---|---|---|---|---|
| 1 | clone: use a qubit twice | **refused** | `linear-use-after-move` | `reject/clone_qubit` |
| 2 | drop: not consumed | **refused** | `linear-value-unconsumed` | `reject/drop_qubit` |
| 3 | use after `measure` | **refused** | `linear-use-after-move` | `reject/use_after_measure` |
| 4 | CNOT, same qubit as control and target | **accepted**, three ways; **traps at run time** | none | `accept/same_handle_cx`, `copied_handle_cx`, `two_handles_one_index` |
| 5 | borrowed qubit escapes its region | **refused** | `reference-escapes-region` | `reject/escape_borrow` |

Per the idea doc's M2 gate: 1, 2, 3 and 5 are refused by existing rules
and 4 is not. **What blocked 4**, exactly: `&!r` is `val` (a copyable
pointer), so `cx(x, x)` and `let y = x; cx(x, y)` pass two copies of one
pointer, and `fresh(2, 0)` twice gives two owned qubits with the same
index, which the checker cannot see because the index is an `int`. The
three variants are pinned as `tests/accept/` files so that the day a rule
refuses one, the build goes red and the file moves to `reject/` on
purpose. The run-time check in `gates.cx` stops all three.

## Further rejections found while writing the fixtures

| Error | Rule tag | Fixture |
|---|---|---|
| qubit consumed on one branch only | `linear-value-unconsumed` | `unconsumed_on_one_branch` |
| `measure` inside a loop | `linear-value-unconsumed` | `measure_in_loop` |
| two unique borrows of one qubit at once | `borrow-conflict` | `two_mutable_borrows` |
| reading `q.idx` from an owned qubit | `linear-value-taken-apart` | `read_qubit_index` |
| a slice of qubits | `mode-bound-violated` | `register_of_qubits` |
| control borrowed `&`, used where `&!` is needed | `type-mismatch` | `control_written` |

## R2 is confirmed: there are no opaque types

A `pub res struct` can be built (`qubit.Qubit { idx: 1, n: 2 }`) and
destructured from any module; `tests/accept/forged_qubit.cho` does it and
gets a working qubit. A non-`pub` struct cannot appear in a `pub`
signature (rule `not-public`), so hiding the constructor is not possible
either. The "only `fresh` mints qubits" guarantee (decision D1) is
therefore a convention, and an agent that writes `Qubit { ... }` directly
is not stopped. If this matters, it is a compiler request: private
fields, or a `pub` type with a hidden constructor.

## R1: how much work do the borrows do?

Linearity (`res`, `measure` consuming) carries entries 1, 2, 3 and the
branch and loop cases: nothing about `&!` is involved. The borrows add
four things, none of them about quantum mechanics:

- an escaped reference to a qubit is refused (entry 5);
- two gates cannot be in flight on one qubit (`borrow-conflict`);
- control and target have different modes, so a control cannot be passed
  where the operand to be modified is expected (`control_written`);
- a gate cannot be applied to a qubit that is gone (entry 3 reaches this
  too, through the `borrow` of a moved value).

The qubit holds no data the borrow could protect (an index only), and the
state vector is borrowed `&!` by every gate regardless. So the honest
reading of R1 is: **no-cloning and no-dropping are real checker results;
the borrow modes are a typing discipline for roles (control versus
target), not a memory-safety result.** That is worth saying in any
write-up.

## What the checker still cannot say

Unchanged from `qubit-types.md` §5, with one addition from writing
`teleport.cho`: the checker does not know that `measure` also changes the
*other* qubits' amplitudes (entanglement), and nothing in the types stops
a program from applying a gate to a qubit that has already been
teleported away, as long as its `Qubit` value still exists. The type
tracks ownership of the handle, not the physical state.

## Verdict against the success criteria (idea doc §7)

- **M2: refused mostly by existing rules.** Yes: 4 of the 5, plus six
  more cases.
- **The gap is specific and recorded:** distinctness of two operands, and
  forging a handle.
- **Do the aliasing and forging gaps justify compiler work?** Both are
  compiler-repo asks with measured cost, if the project continues:
  `aliasing.md` route 1 (same-place twice) would close way 1 of entry #4
  for zero corpus cost, and private constructors would close R2. Neither
  is needed for M3.

## Not done

- No GHZ or larger typed program; `bell` and `teleport` stand for the
  layer, and larger circuits are covered untyped by M1's diff.
- `Qubit` as a handle owned by a simulator (open question 2) was not
  tried; the index design was enough to answer the gate.
- Rule tags are from this compiler revision; they can change.
