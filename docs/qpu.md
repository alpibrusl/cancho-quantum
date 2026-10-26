# M4, first slice: a counted backend (`src/qpu.cho`)

**Status (2026-10-26): a library, not the compiler capability.** The compiler has no `Qpu` (the design is `docs/capability-budget.md` in the compiler repository, answering
cancho#612, merged as a proposal). This slice writes the *semantics* of that design as a library with the compiler's existing `res` types, so that they can be tried, tested and
argued about before the compiler change. Tags: **[measured]** printed by a script or the checker, **[choice]**, **[open]**.

## What it is

```
pub res struct Qpu { backend, bound, left }
qpu.open(backend, bound)                      the root: at most `bound` shots, ever
qpu.run(&!q, st, n, rng, counts, shots)       Ran::Ok(shots) | Ran::Exhausted(left)
qpu.shrink(q, k)                              Narrowed::Narrower(Qpu) | Narrowed::Refused(Qpu)     0 < k < left   (rule N1)
qpu.halve(q, k1, k2)                          Halves::Two(Qpu, Qpu) | Halves::Refused(Qpu)          k1 + k2 <= left (rule N2)
qpu.close(q)                                  the shots it spent
```

* A `Qpu` is a `res`: it cannot be copied (`copy_qpu.cho`: `linear-use-after-move`) or dropped (`drop_qpu.cho`: `linear-value-unconsumed`). A program always ends a budget by saying what it spent.
* `run` takes it as `&!`, because it carries a counter; each call subtracts its shots. If they are more than is left **nothing is submitted** and the answer is `Exhausted(left)`: spending a budget to zero is
  the expected end of a loop, so it is a value to match on, not a trap (the design's §2). Shots outside 1..4096 are a programming error and trap.
* `shrink` and `halve` consume the capability they narrow and return the smaller one(s); the remainder is lost (§3.1). A request that would raise a budget, or narrow it to itself, answers `Refused` with the capability
  back, unchanged. The design refuses these at check time, where the amounts are literals; here they are values, so the refusal is a run-time answer.
* The backend is `qsim`'s own sampler: the program applies its gates to a state vector as ever and `run` draws `shots` outcomes from it into `counts`. **[choice]** This is the "mock backend behind the capability" of the design's §7.

## Tests **[measured]**

`python3 scripts/check_types.py`: 28 of 28 fixtures (24 before; this adds four).

| fixture | what it shows |
|---|---|
| `accept/qpu_budget.cho` | 100 shots; 40 and 40 are run, the third 40 is `Exhausted(20)` and nothing is submitted; the counts of the accepted runs add up to 80 and a Bell pair never disagrees; `shrink` to 10 is accepted, `shrink` of 10 to 10 is refused; the child spends 10; 90 spent, 10 lost in the narrowing |
| `accept/qpu_halves.cho` | `halve` 60 + 60 of 100 is refused and the 100 come back; 60 + 30 is accepted; the first child runs 40 and is refused another 40, the second runs 30: 40 and 30 spent, at most the 100 they came from |
| `reject/drop_qpu.cho` | a `Qpu` that is not given back or closed: `linear-value-unconsumed` |
| `reject/copy_qpu.cho` | a `Qpu` used after `shrink` consumed it: `linear-use-after-move` (two capabilities of 100 from one of 100 would allow 200) |

## What this does not do, against the design's gates **[measured]**

`cancho authority` on `accept/qpu_budget.cho` (compiler `6bb30b4`): `performs heap, io_write; never touches the filesystem, the network, the command line, ...`. There is no `qpu_shots` label and no `limit`,
because the compiler does not know what a `Qpu` is. So of the design's three enforcers:

| layer | design | this slice |
|---|---|---|
| compiler | `shots-exceed-bound` (a literal over the bound), `capability-not-narrowable`, `budget-not-literal`, `budget-split-exceeds`, and a `limit` in `authority --output json` | **none**: a literal 200 through a `Qpu` of 100 compiles, and the run answers `Exhausted` |
| the capability's counter | `qpu_run` refuses with `Exhausted`; no counter, no submission | **yes**, tested above |
| a supervisor | compares the report's per-backend sum with its grant | **no**: there is nothing in the report to compare |

So the first M4 gate, "exceeding granted shots is refused at check time", **is not met**, even for literals, and the claim this slice supports is the design's weaker one: *a declared upper bound, enforced by the
capability's own counter*. It is not a proof about a program, and (as the design says) the counter lives in the program's process: it bounds a program that uses the capability, not one that breaks the runtime.

One more limit: a `pub res struct` can be built from any module (`docs/m2-results.md` R2), so a program can write `qpu.Qpu { backend: 0, bound: 1000000, left: 1000000 }` and mint its own budget. That is
the same hole `forged_qubit.cho` documents for `Qubit`, and the reason the real capability has to come from `split` in the compiler and not from a library.

## Next, in order

1. **The compiler capability** (cancho repository): `Qpu(backend, n)` from `split`, `qpu_run`, the label `qpu_shots` with a `limit`, and the four check-time refusals of the design. This slice's fixtures are written to become its conformance suite (the design's §8).
2. **A real transport behind `run`**: the OpenAPI submission of IBM's Runtime is today a Python script (`scripts/hw_spike.py`) that holds the key itself; a cancho program that builds the request and sends it needs `Net` bounded to the host (`net-bounds.md`) and a TLS client, neither of which this slice assumes.
3. **Time as a second budget**: the Open Plan allows about 600 s of device time per 28 days, which is the budget that bit in practice (`docs/hardware.md`); the design has one numeric limit per label (its §6.3).
