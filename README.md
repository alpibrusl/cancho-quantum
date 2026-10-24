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
- `docs/benchmark.md`: where `qsim` stands against Qiskit Aer and Statevector (speed, memory, the density matrix); build with `--backend llvm` for large circuits, it is 3 to 6 times faster than the default
- `docs/idle-noise.md`: T1/T2 decay while a qubit waits, a gate runs, or it waits for a partner (`coher`, `wait`, `time1`, `time2`, `sched`), checked against Qiskit Aer's thermal-relaxation channel
- `docs/calibration.md`: a real device's published calibration (`ibm_perth`, 2024-05-27) read into a profile, checked against Qiskit Aer's noise model built from the same snapshot (`scripts/calibration_import.py`, `check_calibration.py`)
- `docs/noise-profile.md`: per-qubit and per-pair gate error, asymmetric readout, and a device-style JSON profile file (`tools/qprofile.cho`; `profiles/example_5q.json` has invented numbers)
- `docs/noise-results.md`: five channels, readout error and a gate-noise model, by trajectories, checked against exact density matrices
- `docs/m3-results.md`: M3 results (byte-identical across backends and architectures; provenance)

![The Bell-pair circuit](docs/img/bell-circuit.svg)

![Worst amplitude error against Qiskit, per circuit](docs/img/error-per-circuit.svg)

**What is cancho and what is Python.** The simulator (`src/`) and the tools a user runs (`tools/`: `qprofile`, which
turns a device-style JSON noise profile into `qsim` operations, and `qcalib`, which turns a published IBM calibration into
such a profile) are cancho, with no Python and no file or network access (`cancho authority` says so). Python is only the
test and site tooling: the Qiskit and Aer references that act as independent oracles, the checks, the generators of the test
circuits and the landing-page builder. `scripts/noise_profile.py` and `scripts/calibration_import.py` are reference
implementations the cancho tools are differentially tested against, not what you run.

```sh
cancho build tools/qprofile.cho --std -o qprofile
cancho build tools/qcalib.cho --std -o qcalib
./qcalib < profiles/raw/ibm_perth_props_2024-05-27.json > perth.json       # IBM's published calibration -> a profile
(cat perth.json; echo ---; printf 'dm 3\nh 0\ncx 0 1\ncx 1 2\npurity\n') | ./qprofile | ./qsim   # the circuit, with its noise
```

```sh
cancho build src/*.cho --std -o qsim
printf 'n 2\nh 0\ncx 0 1\n' | ./qsim          # a Bell state

pip install qiskit numpy qiskit-aer qiskit-ibm-runtime   # the last two only for the idle-noise and calibration checks
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

`scripts/check_schedule.py` checks `sched` against Qiskit's ASAP scheduler.
`scripts/idle_curve.py` writes the T1/T2 decay curves the page shows.
`scripts/check_calibration.py` checks the real-device profile against Aer; `scripts/check_tools.py` checks the cancho tools (`tools/`) against their Python reference implementations.
`scripts/check_profile.py` checks the noise-profile converter and the simulator's use of it against Qiskit.
