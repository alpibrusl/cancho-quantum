# Qubit types: what the checker should refuse, and what it cannot

> **Status: M0 design, written before any simulator code.** Compiler
> revision `3fa3fbb` (alpibrusl/cancho). Claims marked **measured** were
> run against that revision with `cancho check --std`; claims marked
> **predicted** were not, and say what would falsify them. Nothing here
> is a claim about what cancho-quantum can do yet.

The question M2 answers is narrow: *which quantum-information errors does
cancho's existing linearity and borrow checker refuse, with no compiler
changes?* This document fixes the design the question is asked of, the
must-reject list, and the answer we expect for each entry, so that M2 can
disagree with us in public.

---

## 1. The mapping

| Quantum fact | cancho mechanism | Enforced by |
|---|---|---|
| No-cloning | `Qubit` is `res`: one use, no implicit copy | `linear-use-after-move` |
| Discarding is not free | no `drop`: a `res` must be consumed on every path | `linear-value-unconsumed` |
| Measurement collapses the qubit | `measure` takes `Qubit` by value; the result is a `val` `int` | both of the above |
| Applying a gate keeps the qubit | gate borrows (`&!`) the qubit | `borrow-conflict` |
| Control is read, target is written | control `&c`, target `&!t` | `borrow-conflict` |
| A qubit cannot outlive its simulator | reference may not outlive its region | `reference-escapes-region` |
| **Two operands of a gate are different qubits** | **nothing** (see §4) | **not enforced** |

The last row is the finding this document exists to state early. No-cloning
(one qubit, one use) and *distinctness* (two qubit operands are two qubits)
are different properties. Linearity gives the first. The second is a
statement about aliasing, and `&!` in cancho is a lock on a binding, not a
uniqueness guarantee (`cancho/docs/aliasing.md`).

---

## 2. The design under test

### 2.1 `Qubit` is an index; the amplitudes are threaded

```
res struct Qubit { idx: int }
```

The state vector is a `[float]` of `2^(n+1)` interleaved (re, im) values
passed to every gate as a `&!s [float]` parameter. A **struct cannot name a
region** (`aliasing.md` §3, route 2), so a `Sim` struct cannot hold a
borrowed slice. The alternative is `res struct Sim { amp: Box[[float]] }`,
which owns the buffer on the heap (`boxed-slices.md`) and shows `heap` in
the effect row and in `cancho authority`. M1 builds the threaded form;
the owning form is an M2 experiment if the threaded one is clumsy.

### 2.2 Operations

```
fn h[&a, &s](q: &!a Qubit, st: &!s [float]) -> [] int
fn cnot[&c, &t, &s](ctl: &c Qubit, tgt: &!t Qubit, st: &!s [float]) -> [] int
fn measure[&s](q: Qubit, st: &!s [float]) -> [] int      // consumes q
```

Return values here are `int` placeholders; M1 decides the real shape.

### 2.3 Honest note on what the qubit borrows are worth

A `Qubit` carries only an integer. Borrowing it `&!` while the simulator
slice is *also* `&!` means the qubit borrow protects no data: every gate
already holds exclusive access to the amplitudes. The qubit borrows are
therefore a **typing discipline** (control versus target, a qubit that
cannot be used while a gate on it is in flight), not memory safety.
That is still the thing being tested, but it should not be dressed up as
more. The alternative that makes the borrow carry weight (the qubit
owns its slice of the state) does not exist for an entangled state, which
is not a product of per-qubit states.

---

## 3. Decisions taken in M0

These were open questions in the idea doc (§11). Each is decided so M1
can start; each lists what would reverse it.

**D1. `Qubit` is an index minted by the simulator, not owned by a `Qpu`.**
Cheapest design that can falsify the thesis (question 2). Constructors are
not exported: the only way to get a `Qubit` is `alloc_qubits`, which hands
out distinct indices. This closes "two live handles to one index" by
construction. Reversed if M2 shows the minting function cannot be made the
only constructor (cancho has no module-private fields to enforce it; see
§7, risk R2).

**D2. Entropy is a value, not a capability.** The sampler is a PRNG state
passed as `&!p [int]`, seeded by the caller. This keeps measurement inside
cancho's defined behaviour with no new effect label, and `[rand]` does not
exist today (no such label in `cancho/docs/`). A dedicated capability is
only worth designing if M4 needs it. Reversed if the PoC wants the
authority report to show "this program samples".

**D3. `measure` is the only consumer of a `Qubit`.** There is no separate
`discard`. A bit is `val`, so ignoring `measure`'s result is already legal.
That is a sampled outcome, not a true partial trace (a state vector cannot
represent the mixed state left behind); the doc says so wherever it
matters. A checked "known |0>" uncompute (Silq-style) is a different
project and a non-goal. Reversed if a program needs `reset`.

**D4. Gates are not values.** cancho refuses function values
(`effect-polymorphism.md` §2). Circuits are data (a gate list interpreted
by the simulator), not higher-order functions. `adjoint` and `controlled`
transforms are therefore out of scope and must not be promised.

**D5. Bit order is little-endian** (qubit 0 is the least significant
bit), matching Qiskit, and recorded in the reference-generation script so
diffs do not turn on convention.

**D6. Tolerance 1e-12 against Qiskit/Cirq reference vectors.** cancho's
`sin`/`cos` are fdlibm ports, measured at 1 ulp near multiples of π/2 and
2 ulp up to 10^6 against libm (`float-math.md` §8). 1e-12 absolute is
roughly four orders of magnitude above that. The ulp error observed in RZ
is recorded in M1, not assumed.

---

## 4. The must-reject list, with predicted and measured outcomes

All five were attempted against the §2 design at `3fa3fbb`. Probe sources
are in Appendix A.

| # | Error | Expected | Measured | Rule tag |
|---|---|---|---|---|
| 1 | Clone: use a qubit twice (`measure(q); measure(q)`) | refused | **refused** | `linear-use-after-move` |
| 2 | Drop: qubit not consumed on some path | refused | **refused** | `linear-value-unconsumed` |
| 3 | Use after `measure` (borrow a consumed qubit) | refused | **refused** | `linear-use-after-move` |
| 4 | CNOT with one qubit as control and target | **not refused** | **accepted, three ways** | none |
| 5 | Return a borrowed qubit out of its region | refused | **refused** | `reference-escapes-region` |

### 4.1 Reject 4, in detail

Accepted by the checker today, each a distinct way:

1. **Same handle twice.** `borrow mut q as &!c in { cnot(c, c, st); }`.
   `c` is passed as both control and target. `&!r` is `val`, so passing
   it twice passes two copies of one pointer (`aliasing.md` §3, route 1).
2. **A copy.** `let d = c; cnot(c, d, st);` (route 2).
3. **Two handles, one index.** `let b = alloc_q(0)` after a first
   `alloc_q(0)`: two live `Qubit` values with the same `idx`. D1 closes
   this one (minted indices), but only if the constructor is genuinely
   unreachable, which cancho cannot enforce (R2).

So the thesis is **false as stated for distinctness** and true for
no-cloning. This is a finding recorded now, as the idea doc asked (§6,
M2), not a failure of the milestone.

### 4.2 What would close it

In increasing cost:

- **Runtime check in `cnot`**: trap when `ctl.idx == tgt.idx`. Cheap,
  defined behaviour, and the program cannot proceed. It is a trap, not a
  check-time refusal, so it does not count toward the authority claim
  and must not be reported as one.
- **`aliasing.md` route 1** (no two reference arguments of one call share
  a root place). Closes way 1 only. Costs zero call sites in the
  existing corpus; a compiler change, so gated on M2 being positive and
  on a design doc in the compiler repo.
- **Route 2** (a `&!` stops being `val`; copies become moves with implicit
  reborrows). Closes way 2. A research budget, not a pass
  (`aliasing.md` §3).

M2's job is to say which of these the quantum use case actually needs.
M0's prediction: the runtime check, plus D1, is the right PoC, and route 1
is the interesting compiler ask.

---

## 5. What the checker cannot express

Recorded so a later milestone is not judged against a promise.

1. **Distinct operands.** §4.1.
2. **Entanglement.** A qubit's state depends on others; linear ownership of
   `Qubit` says nothing about this. A `measure` on one qubit changes the
   amplitudes seen by every other. The type layer does not model it,
   and should not pretend to.
3. **Qubit count at the type level.** `n` is a runtime value. A program
   indexing past `n` is a bounds trap, not a type error. Dependent sizes
   are not available.
4. **Adjoint, controlled, and any function-valued gate.** D4.
5. **True partial trace.** D3.
6. **Statically bounded shots.** Constant shot counts can be bounded from
   the program text; a loop that submits `N` jobs cannot. The M4 claim is
   likely "a declared upper bound the supervisor enforces" (the
   `under-a-grant.md` model), not a type-level proof. Capability bounds in
   cancho today are path and host prefixes, not decreasing integer
   budgets. M4 must start from that fact.

---

## 6. Expected shape of the checker's output

Every refusal in the table above prints a stable rule tag
(`cancho_syntax::Rule`). M2 turns each of the five into a
`tests/reject/` fixture carrying `//~ ERROR` and `//~ RULE` lines, in the
format the compiler repo uses. Reject 4 is instead a `tests/accept/`
fixture pinned to its current behaviour, with a comment saying the day a
rule refuses it, it moves to `tests/reject/` on purpose. This is the
convention `aliasing_same_place_twice.cho` already follows.

---

## 7. Risks

- **R1. `&!` on a qubit adds no safety** (§2.3). If M2 shows every
  rejection in §4 is achieved by linearity alone and the borrows do
  nothing, say so: the contribution shrinks to "no-cloning is a `res`".
- **R2. No private constructors.** Nothing stops code from writing
  `Qubit { idx: 0 }` directly, so D1 relies on convention. M2 should
  check whether a `res struct` can be made unconstructible outside a
  module; if not, the minting guarantee is advisory.
- **R3. Aliasing through slices of references**
  (`aliasing_in_a_slice_of_references.cho`) means a register stored as
  `[ &!r Qubit ]` can alias silently. Registers should be owned `res`
  aggregates, not slices of borrows.
- **R4. Float contraction.** M3's bit-identical claim across Cranelift and
  LLVM depends on neither backend fusing multiply-add. This is checkable
  now and should be checked in M1, not discovered in M3.

---

## 8. Next

- **M1** can start. It needs: complex as a two-float struct, the
  threaded state slice (§2.1), H/X/CNOT/RZ, the PRNG (D2), and
  `scripts/gen_reference.py` with D5's bit order and D6's tolerance.
- Open for M1 to settle: whether a zero-initialised `Box[[float]]` state
  (`zeroed-slices.md`, `calloc`) is writable through `&!`, since
  `contents` is documented as returning a shared reference.
- The compiler is untouched until M2 reports.

---

## Appendix A. Probes (revision `3fa3fbb`)

Common prelude:

```
res struct Qubit { idx: int }
fn alloc_q(i: int) -> [] Qubit { return Qubit { idx: i }; }
fn h[&a, &s](q: &!a Qubit, st: &!s [float]) -> [] int { st[q.idx] = 1.0; return 0; }
fn cnot[&c, &t, &s](ctl: &c Qubit, tgt: &!t Qubit, st: &!s [float]) -> [] int {
    st[tgt.idx] = st[ctl.idx]; return 0;
}
fn measure[&s](q: Qubit, st: &!s [float]) -> [] int {
    let Qubit { idx } = q;
    if st[idx] > 0.5 { return 1; }
    return 0;
}
```

Probe bodies and the first line of compiler output:

```
// 1. clone
fn t[&s](q: Qubit, st: &!s [float]) -> [] int {
    let a = measure(q, st); let b = measure(q, st); return a + b; }
  -> error: `q` has already been consumed; a `res` value is used exactly once

// 2. drop
fn t[&s](q: Qubit, st: &!s [float]) -> [] int {
    borrow mut q as &!a in { h(a, st); } return 0; }
  -> error: `q` is still live here; a `res` value must be consumed on every path

// 3. use after measure
fn t[&s](q: Qubit, st: &!s [float]) -> [] int {
    let a = measure(q, st); borrow mut q as &!x in { h(x, st); } return a; }
  -> error: `q` has already been consumed; there is nothing left to borrow

// 4a. same handle as control and target           -> accepted
fn t[&s](q: Qubit, st: &!s [float]) -> [] int {
    borrow mut q as &!c in { cnot(c, c, st); } return measure(q, st); }

// 4b. a copied handle                              -> accepted
    borrow mut q as &!c in { let d = c; cnot(c, d, st); }

// 4c. two live qubits, one index                   -> accepted
fn t[&s](a: Qubit, st: &!s [float]) -> [] int {
    let b = alloc_q(0);
    borrow a as &c in { borrow mut b as &!x in { cnot(c, x, st); } }
    return measure(a, st) + measure(b, st); }

// 5. escape
fn esc[&a](q: &a Qubit) -> [] &a Qubit { return q; }
fn t[&s](q: Qubit, st: &!s [float]) -> [] int {
    borrow q as &x in { return esc(x); } }
  -> error: this returns a reference into `x`, which is a `borrow` block in
     this function; a reference may not outlive its region
```

Caveats on the probes. They run `cancho check`, not `cancho run`; they show
what is accepted, not what the program does. Probe 5's refusal is
reported at the `return`; a separate probe that copies a `val` field out of
the reference (`k = y.idx`) is correctly accepted, because an `int` is not
a reference, and is not an escape. The rule tags in §4 were read from
`cancho check --output json` on probes 1, 2, 3 and 5 (the `"rule"`
field); the plain-text output does not print them.
