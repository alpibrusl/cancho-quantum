# Running on a real quantum computer

Nothing in cancho-quantum has been run on hardware yet. Every check so far compares `qsim` with Qiskit or Aer, and the
noise model was fitted to published calibration numbers, never to a measured run. This is the plan for the first
measurement, and what it is for.

## The experiment

`scripts/hw_spike.py` takes seven circuits that already exist in `tests/qasm/` (Bell, GHZ 3/5/7, Toffoli, QFT-4, a random
5-qubit one), lets Qiskit's transpiler fit them to the device, and runs them as one job. We do not transpile: that is a
project of its own (decomposing to the device's native gates and routing around its connectivity) and is not worth building
before the thin path shows what it has to meet.

For each circuit it records the device's counts, the exact ideal distribution, and what Aer gives with the noise model
Qiskit builds from the same device. `analyze` prints the total-variation distance from the ideal distribution of each, and
a floor: what perfect hardware would still show from finite shots.

What would be learned:

| result | meaning |
|---|---|
| device close to Aer's noise model | the kind of noise `qsim` models (depolarizing, relaxation, readout) is most of what a real device does at this size |
| device far above it | something is missing from the model: crosstalk, correlated errors, drift, leakage. Which circuits are worst says which |
| device near the floor | the circuit is too small to see noise; use a deeper one |

Only then is it known whether the next work is the noise model (crosstalk, gate-type noise) or something else. A noisy
`qsim` run built from the device's calibration (`tools/qcalib.cho`) is the third comparison, and needs the transpiled
circuit's qubit layout mapped back to the profile; that is the next step after the first numbers.

Not testable without an account: the script's `--fake FakePerth` mode runs the whole path with Aer plus the fake device's
noise standing in for the hardware (and says so in the file it writes, which is meant for testing the script, not for
committing). The submission to a real device has not been run: this repository was developed in a sandbox with no access to one.

## Where to register

**IBM Quantum Platform**, <https://quantum.cloud.ibm.com> (the first choice: the calibration data this repository already
uses is IBM's, and `qiskit-ibm-runtime` is installed for it).

1. Create an IBMid and sign in at <https://quantum.cloud.ibm.com>.
2. Choose the **Open Plan**: free, about 10 minutes of device time in a rolling 28-day window, instances in the `us-east`
   region only. A run of these seven circuits takes seconds of device time. Queue waits on the free plan can be minutes to hours.
3. Copy your API key from the dashboard.
4. `pip install qiskit qiskit-aer qiskit-ibm-runtime`, then
   `export QISKIT_IBM_TOKEN=...` (never commit it) and `python3 scripts/hw_spike.py run --shots 2000`.

The plan's terms change (IBM adjusted them in March 2026, and offers a one-time larger allowance after 20 minutes of use);
read the current ones on the site before relying on the numbers here.

## Free or nearly free alternatives

| service | what is free (as of October 2026; check each) | note |
|---|---|---|
| IBM Quantum Platform | Open Plan: ~10 min of QPU time per 28 days | superconducting, 100+ qubits; the plan above |
| qBraid with Quantum Rings | $50 of QPU credit for new users, another $50 every 90 days | reaches IonQ, Rigetti, IQM and AQT hardware through one account |
| Azure Quantum | credits for new customers (Microsoft lists $500 for Rigetti targets; an older post says $500 per provider) | IonQ, Quantinuum and Rigetti behind one account; the credit terms have changed before |
| Amazon Braket | a free local simulator and an hour a month of managed simulators for the first year; hardware is paid per task and shot | no free QPU |
| IonQ, Quantinuum direct | simulators only, or through the services above | |
| Google Quantum AI | approved researchers only | |

The ion-trap machines (IonQ, Quantinuum) are the more interesting second target: all-to-all connectivity means almost no
routing, and a different noise (no T1 decay to speak of, gate-dominated), so the same circuits test the model's assumptions
from the other side. Their native gates differ from IBM's, so the script would take a different transpilation path (the
vendor's, or Qiskit's through a provider package).

Sources: IBM's [plans overview](https://quantum.cloud.ibm.com/docs/guides/plans-overview) and
[March 2026 Open Plan news](https://quantum.cloud.ibm.com/announcements/en/product-updates/2026-03-16-open-plan-news);
[qBraid and Quantum Rings](https://quantumzeitgeist.com/qbraid-qpu-compute-quantum-rings/);
[Azure Quantum pricing](https://learn.microsoft.com/azure/quantum/pricing).

## What to send back

The file `scripts/hw_spike.py run` writes in `docs/data/hardware/` (it holds the device name, date, shots, job id and the
counts; no credentials). Commit it, and the measured numbers go into this document: where they match, where they do not,
and what that means for the model.
