# Running on a real quantum computer

The first measurement was made on 2026-10-26 (`ibm_fez`; the results are in the last section). Until then every check
compared `qsim` with Qiskit or Aer, and the noise model was fitted to published calibration numbers, never to a measured
run. This is the plan for the measurement, and what it is for.

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
committing). The script was first written in a sandbox with no access to a device; the real run is below.

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

## First measurement: `ibm_fez`, 2026-10-26

`python3 scripts/hw_spike.py run --shots 2000 --backend ibm_fez` (job `dbfh4nvpc3tc739nfppg`, Open Plan, a few seconds
of device time; the file is `docs/data/hardware/ibm_fez-2026-10-26.json`). `ibm_fez` is a 156-qubit Heron whose native
gates are `rz`, `sx`, `x` and `cz`, not the `cx` of the Falcon device the earlier calibration check used. Qiskit's
transpiler placed the circuits on physical qubits 0..6, 21..23, 140..143 and 20..24.

Total-variation distance from the exact ideal distribution (the floor is what perfect hardware shows from 2000 shots):

| circuit | `cz` | device | Aer noise model | `qsim` | floor |
|---|---|---|---|---|---|
| bell | 1 | 0.0945 | 0.0505 | 0.0574 | 0.0010 |
| ghz3 | 2 | 0.1185 | 0.0640 | 0.0654 | 0.0125 |
| ghz5 | 4 | 0.1650 | 0.1110 | 0.1165 | 0.0105 |
| ghz7 | 6 | 0.2235 | 0.1480 | 0.1463 | 0.0190 |
| toffoli | 9 | 0.1390 | 0.0455 | 0.0597 | 0.0000 |
| qft4 | 27 | 0.0490 | 0.0330 | 0.0078 | 0.0260 |
| random5 | 34 | 0.0983 | 0.0659 | 0.0581 | 0.0496 |

(The `two_qubit_gates` field in the JSON file counts the final barrier as a two-qubit gate, so it is one too high for every
circuit; `hw_spike.py` is fixed, the recorded file is left as it was written. The `cz`
column above is the count of `cz` in the transpiled circuits.)

**`qsim`** is `hw model` (`tools/hw/`, cancho; `scripts/hw_model.py` is the Python reference it agrees with to 1e-9): the transpiled circuits read back from the job and the device's properties,
converted gate by gate as in `calibration.md` (`rz` free; `sx`/`x`/`cz` with their duration, T1/T2 decay and the depolarizing
rate left after the decay is taken out; readout error per qubit), run on the exact density matrix. It is exact, so it has
no sampling floor; Aer's and the device's columns are 2000-shot samples. The calibration is the one fetched after the job (08:10 that
day, before the job at 08:42), which may not be the one in force when it ran.

What it shows:

- **The device is worse than the model on every circuit that can show it**, by a factor of 1.4 to 1.8 on Bell, the GHZ
  ladder and random5, and 2.3 on Toffoli. Roughly 30 to 55% of the error is not in the calibration-fitted noise model.
- **`qsim` and Aer agree where they should**: bell to ghz7 within 0.007, and Toffoli and random5 within 0.014 and
  0.008. They share the same missing physics, which is the point of the comparison: the gap to the device is not a `qsim` bug.
- **GHZ error grows with size** (0.12, 0.17, 0.22 for 3, 5, 7 qubits) faster than the model's (0.065, 0.117, 0.146):
  consistent with correlated errors or crosstalk, not proved by this run.
- **qft4 and random5 are close to or inside the floor** and say nothing; use deeper circuits with a more concentrated output.

Not established: this is one job, on one day, on one placement of qubits. The calibration is not the one in force during the
job. Drift, the choice of qubits and the 2000-shot noise (about 0.01 to 0.05 in TVD) are not separated from the model's error.
The difference between `qsim` and Aer on Toffoli (0.014) and qft4 is not explained.

Next: repeat on other days and placements, add circuits that expose correlation (GHZ parity, mirror circuits), and add
a crosstalk term to see how much of the gap it closes.

## Second round: mirror circuits, two devices, two placements (2026-10-26)

A mirror circuit is U, a barrier and U inverse, so the ideal output is all zeros and the distance from it is the
error the circuit accumulated, without a wide distribution hiding it in the shot noise. `hw_spike.py run --set mirror`
runs six: the GHZ state of 3, 5 and 7 qubits with its inverse (`ghzm3/5/7`, 4, 8 and 12 `cz`) and random 5-qubit circuits of
2, 4 and 8 layers (`rmir5_d2/4/8`, 8, 16 and 32 `cz`). `--start k` puts each on a line of connected qubits from `k`; `--seed`
changes the transpiler's choice. Each job is 2000 shots. `hw_model.py` then runs `qsim` as before. TVD from all zeros:

| circuit | fez, qubits 0-6: device / Aer / `qsim` | fez, from 60: device / Aer / `qsim` | kingston, from 60: device / Aer / `qsim` |
|---|---|---|---|
| ghzm3 | 0.169 / 0.090 / 0.076 | 0.250 / 0.098 / 0.094 | 0.041 / 0.030 / 0.024 |
| ghzm5 | 0.350 / 0.158 / 0.137 | 0.317 / 0.172 / 0.164 | 0.069 / 0.081 / 0.075 |
| ghzm7 | 0.539 / 0.191 / 0.176 | 0.420 / 0.282 / 0.308 | 0.146 / 0.136 / 0.137 |
| rmir5_d2 | 0.217 / 0.156 / 0.126 | 0.312 / 0.164 / 0.144 | 0.058 / 0.076 / 0.063 |
| rmir5_d4 | 0.260 / 0.206 / 0.183 | 0.341 / 0.198 / 0.181 | 0.081 / 0.093 / 0.081 |
| rmir5_d8 | 0.546 / 0.298 / 0.288 | 0.390 / 0.262 / 0.253 | 0.125 / 0.125 / 0.121 |

(Files: `docs/data/hardware/<device>-2026-10-26-mirror[-from60].json`, with `-circuits`, `-props` and `-qsim` beside each.
The jobs are `dbfhel0m94ac738tj4og` and `dbfhg17sstms73fds6l0` for fez, `dbfhfovsstms73fds690` for kingston from 60.)

**A faulty qubit.** The first kingston job (transpiler's choice, qubits 0-4; `ibm_kingston-2026-10-26-mirror.json`) came back with
TVD 0.84 to 0.87 on every circuit, from one bit: qubit 0 read 1 in 82% of the shots. An idle measurement of qubits 0-4
(`ibm_kingston-2026-10-26-diagnostic.json`, job `dbfhfcnpc3tc739ng8l0`) gave `00001` 83% of the time, and the same `ghzm3` on
qubits 60-62 gave `000` 96% of the time. The calibration published for qubit 0 that morning looks healthy (readout error 0.6%, T1
250 us), so nothing in it warns of the fault. That first file is kept as evidence and is not a measurement of the model.

What the numbers say:

- **On kingston away from the bad qubit, the device is close to the calibration-fitted model** (Aer, and `qsim` with it): within
  0.03 in total-variation distance on every circuit, up to 32 `cz`. *(Corrected 2026-10-26, after the chi-square test of the last section:
  this said "the device matches the model; the model's noise is the whole story there". A distance of 0.02 is small, but at 2000 shots it is
  detectable: the counts are statistically inconsistent with the model on every circuit of every run, kingston's included.)*
- **On fez the device is 1.3 to 2.9 times worse than the model, on both placements.** So the fez gap of the first round is not
  specific to qubits 0-6, nor to the circuits: it follows the device on this day. It is not a general failure of the noise model.
- **The gap on fez does not grow cleanly with width** (ghzm7 on qubits 0-6 is the worst at 0.54 against 0.19; from 60 it is
  0.42 against 0.28 to 0.31), so the round-one reading ("GHZ error grows faster than the model, perhaps crosstalk") is not
  supported as a general claim. The data fit a device-level cause as well.
- **A candidate cause, since refuted:** that the fez calibration was stale when the jobs ran. (This was first written with the
  time zones mixed: job times in the JSON are UTC, calibration times are +01:00. Both devices had been recalibrated, fez at 09:36 and
  kingston at 08:34 local, 27 minutes and 1.5 hours before the mirror jobs, though fez's T1 and readout entries were older.) The third round
  below tests it.
- **`qsim` and Aer still agree** (0.01 to 0.05 TVD between them, mostly the 2000-shot noise of Aer's sample) on all
  three sets. So the density-matrix model reproduces the standard tool's noise model on a native-gate circuit of a different device.

Not established at this point: why fez is worse. See the third round.

## Third round: right after a calibration (2026-10-26, about 11:00 local)

Same mirror set, same placement (a line from qubit 60), about an hour after the second round and 17 to 70 minutes after a new calibration
(fez 10:43, kingston 10:45 local). Files: `*-mirror-from60-1000*.json`; jobs `dbfi8u7sstms73fdtb8g` (fez) and `dbfi9c8m94ac738tk9h0` (kingston).
TVD from all zeros, device / Aer / `qsim`; "before" is the device's value in the second round:

| circuit | fez, now | fez, before | kingston, now | kingston, before |
|---|---|---|---|---|
| ghzm3 | 0.179 / 0.222 / 0.261 | 0.250 | 0.042 / 0.030 / 0.024 | 0.041 |
| ghzm5 | 0.211 / 0.294 / 0.295 | 0.317 | 0.081 / 0.081 / 0.075 | 0.069 |
| ghzm7 | 0.329 / 0.375 / 0.365 | 0.420 | 0.148 / 0.136 / 0.137 | 0.146 |
| rmir5_d2 | 0.211 / 0.288 / 0.279 | 0.312 | 0.063 / 0.076 / 0.063 | 0.058 |
| rmir5_d4 | 0.259 / 0.317 / 0.310 | 0.341 | 0.086 / 0.093 / 0.081 | 0.081 |
| rmir5_d8 | 0.307 / 0.369 / 0.370 | 0.390 | 0.113 / 0.125 / 0.121 | 0.125 |

- **Kingston repeats**: device and model are unchanged within the distance's sampling noise, and the model is close to the device again (*corrected: "matches"; see the last section*).
- **Fez moved both ways at once.** The device improved by 20 to 30% from the second round, while its own calibration got *worse*:
  Aer's prediction for `ghzm3` went from 0.098 to 0.222. The model that under-predicted the device by up to 2.9 times in the morning now
  over-predicts it by 1.2 to 1.6 times. So a fresher calibration did not close the gap on fez; the calibration numbers of this device
  changed by more than its behaviour did, and the sign of the error flipped.
- **So the missing term is not a constant offset, and not just age.** Whatever the model leaves out of fez (the calibration's scatter
  between updates, the device drifting within the hour, or both) is larger than anything it leaves out of kingston. This run cannot say which.
- **`qsim` and Aer agree to within 0.01 to 0.10** (up to 0.10 on `ghzm7` for fez, where Aer's shot noise is not the cause: on the larger
  gate errors of this calibration the two diverge more; not explained).

What this settles: at this size, on a healthy device, the noise model (depolarizing after the decay is subtracted, T1/T2, readout)
is close: kingston, twice, within 0.03 (*corrected 2026-10-26: this said "is enough"; the chi-square test of the last section shows the counts are
not consistent with it, only near it*). On fez it is not reliable in either direction. What it does not settle: the cause. A test would run the same
circuits on fez every hour for a day and plot device against model; if the model's error follows the calibration's jumps, the right fix is to
estimate error rates from the circuits themselves (a short mirror calibration run before the real one), not a better model.

## Pre-flight: reading the qubits before a run

On 2026-10-26 `ibm_kingston`'s qubit 0 read 1 in 82 to 84% of idle shots, and the calibration published that morning gave no sign
of it (readout error 0.6%, T1 250 us). The first job on it was lost to the fault. `hw_spike.py` now checks for that:

- `python3 scripts/hw_spike.py check [--backend D] [--qubits 0,1,2]` reads every qubit (or those listed) idle and again after an X
  gate, in one job of two circuits, and writes `docs/data/hardware/<device>-<time>-readout.json`. A qubit that reads the wrong value more than
  15% of the time is **bad**, more than 5% **weak**. Exit status 1 if any is bad.
- `hw_spike.py run` does the same for the qubits its circuits use, before the real job, and stops if one is bad (`--no-preflight` skips
  it). It costs one more job of two short circuits.
- `python3 scripts/check_hw_spike.py` tests the check offline: a fake device with one qubit stuck at 1 and one stuck at 0 is
  given to `scan`, and it has to name exactly those two. It has not been run against a real device yet; the thresholds are
  chosen from the one fault seen (82 to 84%), so 5% and 15% are judgement, not measurement.

The numbers the landing page quotes from these runs are in `docs/data/hardware_summary.json`, computed from the files
by `scripts/hw_summary.py` (`--check` fails when they are stale).

## Read-out error mitigation (`tools/qmitigate.cho`)

The device's read-out error is the largest single part of the error in the shortest circuits, and it is the one part that can be
measured and undone without a better model. `tools/qmitigate.cho` takes the counts and each qubit's `[p01, p10]` and inverts the
per-qubit confusion matrices (independent qubits); `scripts/mitigate.py` is its reference, `scripts/check_mitigate.py` compares them
(400 random inputs to 1e-12, 18 refused inputs, and known distributions pushed through known errors and recovered to 1e-6;
a deliberate sign error in the tool makes three of the four checks fail). `scripts/hw_mitigate.py` applies it to a hardware file.

Applied to the 2026-10-26 runs, with the errors taken from the device's published calibration (not fitted to these counts), the
distance from the ideal output fell on every circuit of every file (31 of 31):

| file | circuits improved | example (before -> after) | most clipped mass |
|---|---|---|---|
| fez, first spike set (Bell, GHZ, Toffoli, QFT, random) | 7 of 7 | bell 0.095 -> 0.051, ghz5 0.165 -> 0.105 | 0.03 |
| kingston, mirror, from 60, two rounds | 12 of 12 | ghzm7 0.146 -> 0.092, rmir5_d2 0.058 -> 0.031 | 0.03 |
| fez, mirror, from 60, second round | 6 of 6 | ghzm3 0.250 -> 0.192 | 0.06 |
| fez, mirror, from 60, third round (after a recalibration) | 6 of 6 | ghzm3 0.159 -> 0.034 | **0.20** |

Read the last row with care. The "clipped" column is the negative probability the inversion produced and the tool removed. It is
near 0 when the errors it was given are about right and large when they overstate the real ones: the correction overshoots, some
outcomes go negative, and the result is no longer a trustworthy estimate even where its distance to the ideal looks good. That is
the fez calibration of the third round, which is also the one that made Aer over-predict the device (above). So `clipped` is a
second, cheap check on whether a published calibration is in line with the device at that moment. The errors measured by
`hw_spike.py check` just before a run (`hw_mitigate.py --readout FILE`) are the better input, and are the next hardware test.

Not shown: the distance after mitigation is not the model's error (the model includes read-out error itself, so it is
compared before correction); mitigation helps the circuits whose ideal output is concentrated, as mirror circuits' is, more than
spread-out ones; and it does nothing for gate error. 2000 shots, one day, two devices.

## What is wrong with `ibm_fez`: one qubit, found by fitting (`scripts/hw_fit.py`)

The third round said the calibration-based model was wrong on fez "in either direction" and the cause was unknown. The error does not
grow with the circuit: on the morning round the model's distance from the device is 0.16 to 0.20 for every circuit, a 4-`cz` GHZ and a
32-`cz` random one alike. A per-qubit look at the counts (the circuits' ideal output is all zeros, so any 1 is error) shows where it is:

| fez, mirror circuits from qubit 60 | P(read 1) on qubit 60 | its published P(read 1 given 0) |
|---|---|---|
| morning round | 0.20 (ghzm3), 0.26 (ghzm7) | 0.031 |
| after the 10:43 recalibration | 0.10 and 0.08, 0.16 and 0.18 | 0.197 |

(In the first round, on qubits from 0, qubit 0 did the same: 0.41 in `ghzm7` against 0.017 published.) One qubit that reads wrongly
a fifth of the time, with a calibration that is wrong in the morning and, after it was updated, wrong the other way. The pre-flight above would
have called it weak or bad (more than 5% or 15%), and flagged it before the run.

`scripts/hw_fit.py` (and `hw fit`, its cancho port, which uses cancho-opt's Nelder-Mead where the script used scipy's: same 118 evaluations and the same factors to 1e-16 on this run, `scripts/check_hw.py`) tests whether that is enough. It fits some of the model's numbers to three circuits of one job (`ghzm3`, `rmir5_d2`,
`rmir5_d4`; Pearson chi-square misfit, Nelder-Mead, pulled towards the calibration by a prior) and reports, for the three circuits left out, and
for the later rounds, the distance between the model's distribution and the device's counts (a perfect model still shows 0.01 to 0.05 at 2000 shots).

| fez, morning round, fitted on 3 circuits | fitted on | held out (calibration -> fitted) | the later rounds (calibration -> fitted) |
|---|---|---|---|
| four global factors (T1/T2 decay, one- and two-qubit depolarizing, read-out), 118 runs | misfit 0.63 -> 0.20 | ghzm5 0.18 -> 0.16, ghzm7 0.20 -> 0.28, rmir5_d8 0.17 -> 0.38: **worse** | worse by 0.05 to 0.3 |
| each measured qubit's own P(read 1 given 0), and the two-qubit depolarizing factor, 390 runs | misfit 0.63 -> 0.022 | ghzm5 0.18 -> 0.038, ghzm7 0.20 -> 0.076, rmir5_d8 0.17 -> 0.093 | 0.10 to 0.17, **no change** |

- **Global factors do not work.** The fit trades decay against depolarizing (decay x15, two-qubit depolarizing x0.07: not physical),
  and what it learns does not carry over to the circuits left out. The calibration's rates are not simply off by a common factor.
- **Per-qubit read-out does.** The fit moved qubit 60's from 0.031 to 0.18 (61: 0.031 to 0.053; the others barely moved) and the held-out
  circuits of the same job dropped from 0.17-0.20 to 0.04-0.09, near what sampling allows (*corrected: the chi-square test below says not near enough*). The model is not wrong in its physics on fez; it was given a wrong
  number for one qubit.
- **It does not last.** An hour later, with a new calibration and the qubit reading differently, the same numbers help nothing (0.10 to
  0.17 before and after). So a correction of this kind has to be measured just before the job it is for, which is what the scan is.
- **Kingston, where nothing is wrong:** the same fit with per-qubit read-out moves little (qubit 60: 0.007 to 0.012), improves the
  held-out ghzm5 and ghzm7 (0.025 to 0.018, 0.044 to 0.026), and makes the deepest circuit worse (rmir5_d8 0.029 to 0.042, and again, 0.027 to 0.043, an hour
  later). The two-qubit depolarizing factor came out near 3 on both devices (3.00 and 3.19, with the prior at ln 3 = a factor of 3
  in one sigma), and the deepest circuit getting worse says it is not a clean factor. This is not explained.

Not shown: this is one qubit, one device, one morning, and fitted to counts that were also used to show the problem; the held-out circuits
share the qubits and the minute of the fit. The test that does not share them is `scripts/hw_scan_model.py JOB SCAN`: take a `hw_spike.py check`
of the qubits just before a mirror run and see whether the model, given the scan's read-out errors and nothing fitted, lands within sampling noise of the
device. Run it on a job whose scan was taken before it; `hw_scan_model.py` was tested here only with a made-up scan (one qubit's value set from the fit above),
which checks the plumbing and is not a result.

## Is the model consistent with the counts? A chi-square test (`scripts/hw_gof.py`, with cancho-stats)

Every comparison above is a total-variation distance read against a guessed floor ("0.01 to 0.05 at 2000 shots"). A test knows how much distance 2000 shots
of the model itself would give. `scripts/hw_gof.py` runs `stats test chisq --expected` (the `stats` command of
[cancho-stats](https://github.com/alpibrusl/cancho-stats), built from its pinned compiler) on each circuit's counts against `qsim`'s distribution: an outcome whose
expected count is 5 or more is a level, the rest are pooled. Two controls first: 120 runs of 2000 shots drawn from the model itself gave p < 0.05 in 5.0% of them and
p < 0.001 in none (median p 0.39), and the statistic of one real case, computed by hand, is the tool's (121.1 on 4 degrees of freedom).

| run (2000 shots, six mirror circuits unless noted) | circuits with p < 0.05 | p < 0.001 | median p |
|---|---|---|---|
| kingston, morning, from qubit 60 | 6 of 6 | 6 | 2e-12 |
| kingston, after the 10:43 recalibration (two rounds) | 6 of 6 each | 6 each | 1e-13, 2e-8 |
| fez, qubits 0-6 | 6 of 6 | 6 | 3e-123 |
| fez, from 60, morning and the two later rounds | 6 of 6 each | 6 each | 4e-196, 2e-40, 2e-109 |
| fez, first spike set (Bell, GHZ, Toffoli, QFT, random) | 6 of 7 | 6 | 9e-30 |

**The calibration-based model is rejected by the counts on every run, on both devices.** On kingston the cause is a distance of 0.02: for `ghzm3` the model
puts 1953 of 2000 shots on all zeros, the device returned 1913, 5.9 standard deviations. So "within 0.03" and "inconsistent at p = 1e-25" are both true.
Where this changes what was said: the kingston result is *close*, not *matches*, and the calibration-based model's distribution is about 0.02 (kingston) and 0.16 to 0.20
(fez, before the fit) away from what the device returns in total variation, and neither is shot noise.

What the fits of `hw_fit.py` do to this (fez and kingston, morning, fitted on `ghzm3`, `rmir5_d2`, `rmir5_d4` with per-qubit read-out and the two-qubit factor):

| fez | calibration: chi-square, p | fitted: chi-square, df, p |
|---|---|---|
| ghzm3 (fitted) | 1316, 1e-282 | 14.9, 6, 0.021 |
| rmir5_d2 (fitted) | 1473, 5e-314 | 26.8, 10, 0.003 |
| rmir5_d4 (fitted) | 1014, 2e-208 | 49.9, 17, 4e-5 |
| ghzm5 (held out) | 938, 4e-196 | 39.7, 16, 9e-4 |
| ghzm7 (held out) | 962, 2e-195 | 88.0, 25, 6e-9 |
| rmir5_d8 (held out) | 776, 2e-151 | 86.8, 29, 1e-7 |

On kingston the same fit brings every circuit down (for example `rmir5_d2` 66 to 13, p = 0.12; `rmir5_d4` 24.5 to 13.8, p = 0.18) except the deepest, `rmir5_d8`, which stays
rejected (59 to 45 on 19 degrees of freedom). So on fez the fit removes 89 to 99% of the chi-square and still leaves five of the six circuits rejected: one qubit's read-out
was most of what was wrong, not all. (The fit section above says the held-out circuits came "near what sampling allows"; the p-values show they did not: 0.04 to 0.09 is
above it.)

Limits: `stats` takes its levels from the data, so a level that the counts never show cannot be named; its expected mass is given to the largest level (this
can only make the test less sensitive). The test says the model is not exact, not what is missing. With 2000 shots a difference of a few percent in a probability is already
significant; with 200 it would not be.
