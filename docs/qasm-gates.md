# OpenQASM `gate` definitions: design

Written before the code (`CLAUDE.md`: design before code, claims measured). `src/qasm.cho` reads a subset of OpenQASM 2.0 (`docs/features-results.md`); what it does not read, and what Qiskit writes as soon as a circuit contains a composite gate, is the
`gate name(params) qubits { body }` definition. This is the design of reading it, and of the one thing it needs that the reader does not have: an expression evaluator.

## 1. What Qiskit writes **[measured, Qiskit 2.x `qasm2.dumps`]**

* A circuit with a gate that `qelib1.inc` does not have is written with its definition **before `qreg`**: `ryy`, `iswap`, `ecr`, `dcx`, a user's `to_gate()`, a nested one (`gate outer q0,q1 { my_gate q1,q0; cz q0,q1; }`). `rzz`, `rxx`, `csx`, `cp` are written as calls with no definition.
* The names are long: `gate_QFT`, and for the same circuit's second use `gate_QFT_140039187527760` (24 characters; the two share their first seven). The reader today keeps a statement's first seven characters
  (`word`), so these two names are the same word. **This is a bug today** for any name over seven characters that begins with a built-in's seven (`measured` is `measure`), and the design fixes it (§3).
* Parameters are `param0`, `param1`, ... in library gates (`ryy(param0)` with `rz(param0) q1` in its body); a bound composite gate has its numbers written into the body (`rz(0.123) q1`).
* Sizes: a 6-qubit QFT as a gate is 350 characters of definition; a 5-qubit quantum volume circuit is 10 definitions of up to 517 characters, 5,131 in all. The budget below (24,000 characters) is four to five times that.

## 2. What is read

```
gate name [ ( param, ... ) ] qubit, ... { statement; ... }
```

A statement in a body is a gate call (built in, or one of the gates defined before) with qubit arguments that are the gate's own qubit names, and angle arguments that are **expressions** of the gate's parameters: numbers, `pi`, the parameter names, `+ - * /`, a unary minus,
parentheses, `^`, and `sin cos tan exp ln sqrt` (the full expression grammar of the OpenQASM 2.0 paper). `barrier` in a body is skipped. `U(a,b,c) q;` and `CX a,b;` are read as `u3` and `cx` (a definition of `h` from them is the textbook example), `opaque` is refused. A call has the same arguments, with `q[i]`.

## 3. How: expansion by text, not an environment

The reader pulls characters from standard input through one cell of lookahead (`la`). Three ways to run a body: (a) keep the body as a tree and walk it with an environment (a new data structure and a second operand parser, in a language without closures);
(b) store the text and run it with the formals bound in tables (every operand and expression parser gets a lookup); (c) **store the text, and at each call copy it with the formals replaced, then read the copy as if it were standard input**. Chosen: (c).

* A definition is stored whole in a text arena (`la` itself, an array of ints, which moves from the region to the heap so that it can be 32,000 cells) with a table of 64 entries (start, length). Its name is compared as full text.
* A call evaluates its angle arguments to doubles in the caller's context, then copies the body into the arena above the definitions: every parameter name becomes `(` the value, printed as the shortest decimal that reads back to the same bits (`std.fmt.float_into`), `)`; every qubit name becomes `q[i]` with the
  caller's index; everything else is copied. The copy is a new input frame: the character under the cursor is saved, the cursor moves to the copy, and at its end the saved character is restored. A body ends with `;`, so a frame always ends at a statement boundary and the existing statement reader runs unchanged,
  nested calls included (they push their own frames).
* A value printed and read back is the same double inside the reader's exact range (docs/features-results.md, decimal angles); outside it (an angle of 1e-30, say) it is within 2 ulp, which no amplitude can show.
* The word packed from a name is only used for names of up to seven characters; a longer name is never a built-in (`measured` stops being `measure`), and is looked up in the table by its full text. A user definition of a built-in's name wins over the built-in, as Qiskit's own loader lets it (it is how `qelib1.inc` is itself written).

## 4. The expression evaluator, and why the old angles do not move

Today an angle is read by a grammar of its own (`angle`): a number, `pi`, `N*pi`, `pi/M`, `N*pi/M`, with a sign, and the multiples of pi are kept as `pi * num / den`, the double the references compute, **bit for bit**. The evaluator replaces it, as a recursive descent over
`expr = term {(+|-) term}`, `term = unary {(*|/) unary}`, `unary = (-|+) unary | power`, `power = atom [^ unary]`, `atom = number | pi | name | ( expr ) | function ( expr )`. A value carries what it is: a plain double, an integer (so that `3*pi` stays exact), or a rational multiple of pi
`(num, den)`; the rules are the ones that make the old grammar's results come out of it unchanged: integer `*` pi-multiple is a pi-multiple (num times), pi-multiple `/` integer is a pi-multiple (den times), unary minus keeps the kind, and anything else (`+ - ^`, a function, a decimal, a name bound to a double) is a plain double.
**Claim, to be measured:** on every text the old grammar accepted, the new reader's output is identical to the old reader's, byte for byte (§6, check 1).

## 5. Limits and refusals (each a refusal with a status and a message, never a trap)

| input | answer |
|---|---|
| definition text over 24,000 characters in all, or a 65th definition | status 3, "too many gate definitions" |
| a call that nests more than 8 deep (including a gate that calls itself: it is defined before its body is read, so its own name is a call) | status 3, "gates nested deeper than 8" |
| more than 200,000 gate calls expanded in one run (a chain of gates that each call the one before twice) | status 3, "too many gate calls" |
| a name of more than 63 characters | status 3 |
| a call with a different number of angles or qubits than the definition | status 2 |
| a call of a name that is neither built in nor defined | status 3 "a gate that is not defined" |
| `opaque`; `measure`, `reset`, `if` inside a body; a second definition of the same name | status 3 |
| an expression that divides by zero or is not finite | status 3 |

## 6. What is checked (`scripts/check_qasm.py`), and what is not claimed

1. **The old grammar did not move.** A corpus of 5,000 angle texts of the old grammar (random numerators, denominators, decimals, signs, spellings) is run through the reader built from the last commit before this change and through the new one, and the outputs compared byte for byte.
2. **Qiskit's own definitions.** Random circuits with custom gates, nested, with the names Qiskit chooses, written by `qasm2.dumps`, against its statevector to 1e-12; and the library gates it defines (`ryy`, `iswap`, `ecr`, `dcx`).
3. **Expressions.** 150 random definitions written by hand with parameters in expressions of the full grammar, against `qasm2.loads`' statevector to 1e-12.
4. **Refusals.** Every row of §5 is a text that must be refused with its status (and none may trap); a fuzz of 1,000 mutated programs must end in a status, never a trap.
5. **Mutants.** The check must fail on deliberate bugs in the evaluator (a precedence swap, `^` associating the wrong way, a lost unary minus), in the substitution (a parameter replaced by its text without parentheses, which makes `-param0` and `2*param0` wrong when the value is negative or an expression), and in the frame stack (the saved character not restored).

Not claimed: `rxx`, `csx`, `cu3` as built-ins (they can now be defined in a file, as Qiskit's `qelib1.inc` does); the speed of expansion; that a pathological program (200,000 calls) is quick; arbitrary-precision text for `float_into` (the shortest round-trip is relied on, and is checked, not proved).
