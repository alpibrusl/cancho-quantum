# cancho-quantum

A small quantum state-vector simulator written in [cancho](https://github.com/alpibrusl/cancho),
built to test whether cancho's linear resources and capability-typed
effects fit quantum information. Status: pre-PoC, milestone M1 of the plan
in `docs/qubit-types.md`.

- `docs/qubit-types.md`: M0 design and the must-reject list
- `docs/m1-results.md`: M1 results (simulator, diff against Qiskit)

```sh
cancho build src/*.cho --std -o qsim
printf 'n 2\nh 0\ncx 0 1\n' | ./qsim          # a Bell state

pip install qiskit numpy
python3 scripts/gen_reference.py              # regenerate tests/diff/*.ref
CANCHO=path/to/cancho python3 scripts/check_diff.py [--backend llvm]
```

`check_diff.py` is the M1 gate: amplitudes within 1e-12 of Qiskit on every
circuit in `tests/diff/`, measurement bits exact, and the programs in
`tests/trap/` must stop. It needs a cancho built from compiler revision
`3fa3fbb` or later.
