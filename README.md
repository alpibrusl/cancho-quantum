# cancho-quantum

**Live page: <https://alpibrusl.github.io/cancho-quantum/>**

A small quantum state-vector simulator written in [cancho](https://github.com/alpibrusl/cancho),
built to test whether cancho's linear resources and capability-typed
effects fit quantum information. Status: pre-PoC, milestones M0 to M3 of the plan
in `docs/qubit-types.md`, plus more gates, sampling, OpenQASM input,
algorithms (`docs/features-results.md`), noise by sampling (`docs/noise-results.md`) and exact
noise on the density matrix (`docs/density-results.md`).

- `docs/index.html`: the landing page (for humans, for agents, a gallery of what runs, what is refused and what is planned). Rebuild with `python3 scripts/build_site.py`; `--check` fails if it has drifted from the tools. Serve it with GitHub Pages from `/docs`.
- `docs/llms.txt`, `docs/agent-prompt.md`: the same facts for agents
- `docs/qubit-types.md`: M0 design and the must-reject list
- `docs/m1-results.md`: M1 results (simulator, diff against Qiskit)
- `docs/m2-results.md`: M2 results (linear `Qubit`, the must-reject list)
- `docs/features-results.md`: Y, RX, RY, P, SWAP, Toffoli, controlled phase; `sample`; OpenQASM 2.0 input; QFT, Grover, Bernstein-Vazirani, Deutsch-Jozsa
- `docs/density-results.md`: the exact density matrix (`dm N`, up to 10 qubits), checked against Qiskit's DensityMatrix
- `docs/noise-profile.md`: per-qubit and per-pair gate error, asymmetric readout, and a device-style JSON profile file (`scripts/noise_profile.py`; `profiles/example_5q.json` has invented numbers)
- `docs/noise-results.md`: five channels, readout error and a gate-noise model, by trajectories, checked against exact density matrices
- `docs/m3-results.md`: M3 results (byte-identical across backends and architectures; provenance)

![The Bell-pair circuit](docs/img/bell-circuit.svg)

![Worst amplitude error against Qiskit, per circuit](docs/img/error-per-circuit.svg)

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

`scripts/check_types.py` is the M2 gate: the fixtures in `tests/reject/`
must be refused with exactly the rule tags they name, and the ones in
`tests/accept/` must compile and behave as stated.

`scripts/check_determinism.py [--arm64]` is the M3 gate: every circuit runs
interpreted and compiled, on both backends (and aarch64 under `qemu-user`
with `--arm64`), and the output bytes must match
`tests/golden/outputs.sha256`.

`scripts/check_qasm.py` checks the OpenQASM reader: each file in `tests/qasm/`
is read by Qiskit's parser and by `qsim` and must mean the reference, and
the circuits are written back out by Qiskit and fed to `qsim`.

`scripts/check_noise.py` averages noisy runs over thousands of seeds and compares the result with an exact density-matrix calculation.

`scripts/check_profile.py` checks the noise-profile converter and the simulator's use of it against Qiskit.
