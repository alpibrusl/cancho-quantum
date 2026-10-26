# Noise profiles: per-qubit rates, asymmetric readout, and a device-style file

> **Status: built and measured.** Compiler `3fa3fbb`, Qiskit 2.6.1. Checked by
> `scripts/check_profile.py`, `check_diff.py`, `check_noise.py` and
> `check_determinism.py`.

## What was built

Three operations that override the gate-noise defaults of `noise-results.md`, in both
sampled (`n`) and exact (`dm`) mode and in the compiled circuits:

| Operation | Meaning |
|---|---|
| `gate1err q num den` | depolarizing probability after every one-qubit gate on qubit q (replaces `model1` for that qubit; `0` means none) |
| `gate2err a b num den` | two-qubit depolarizing probability after every two-qubit gate on the pair (a, b), in either order (replaces `model2` for that pair) |
| `readerr q n01 d01 n10 d10` | asymmetric readout error on qubit q: a true 0 is reported 1 with probability n01/d01, a true 1 is reported 0 with probability n10/d10 (replaces the symmetric `readout` for that qubit) |

An override that was set to 0 means probability 0, not "fall back to the default"; an override that
was never set falls back. The parameters live in the sampler's slice (`src/profile.cho` has the layout),
so a compiled circuit calls the same functions as the interpreter. A bit still draws a random number
only when its probability is above zero.

**The profile file.** `tools/qprofile.cho` (cancho; `cancho build tools/qprofile.cho --std -o qprofile`) reads a profile on standard
input and prints these operations; with a line `---` and a circuit after the profile it prints the circuit with them
inserted after its header. Neither it nor `qsim` touches a file, which `cancho authority` confirms.
`scripts/noise_profile.py` is the Python reference implementation it is differentially tested against
(`scripts/check_tools.py`: 400 random profiles, 198 broken ones, byte for byte).

```json
{"qubits": 5,
 "gate1":   {"default": 0.0004, "per_qubit": {"0": 0.0002, "3": 0.0011}},
 "gate2":   {"default": 0.008,  "per_pair":  {"0-1": 0.006, "1-2": 0.011, "3-4": 0.014}},
 "readout": {"default": [0.01, 0.03], "per_qubit": {"4": [0.02, 0.07]}}}
```

The profile also takes idle-noise fields, in nanoseconds:

```json
 "coherence": {"default": [50000, 70000], "per_qubit": {"2": [30000, 40000]}},
 "gate1": {"time_ns": {"default": 36, "per_qubit": {"0": 35}}},
 "gate2": {"time_ns": {"default": 400, "per_pair": {"0-1": 300}}}
```

which become `coher`, `time1` / `dur1`, `time2` / `dur2`. T2 above 2 T1 is refused.

A probability becomes the fraction round(p * 10^6) / 10^6. Probabilities above 1, qubits outside the
device, a pair of one qubit, a readout entry that is not a pair, and a circuit larger than the profile
are refused with a message. **The example (`profiles/example_5q.json`) is invented**: its numbers are of the
size reported for superconducting devices, and none comes from a real machine.

## Measured

1. **Each run is exact, bit for bit.** 5 new circuits (4 seeds of a 3-qubit circuit with per-qubit rates,
   per-pair rates, asymmetric readout, a measurement and `sample`; plus the density-matrix version) agree
   with the Qiskit reference that applies the same random decisions: worst error 2.4e-15 (the density-matrix
   one; the sampled ones 1.1e-16).
2. **The average is the physics.** A 3-qubit circuit with per-qubit and per-pair rates, 4000 seeded runs,
   against the exact density matrix: z 1.34, trace distance 0.013.
3. **Asymmetric readout is binomial.** A true 1 on one qubit misread one time in 10 and a true 0 on another
   one time in 5, 4000 runs: z 0.84.
4. **The converter and the simulator agree with a calculation made from the file.** A 5-qubit GHZ state
   through the example profile on the density matrix matches a Qiskit calculation built from the JSON directly
   (never from the converter's output) to 4.4e-16; the converter's output is checked in and compared byte for byte.
5. **Refactoring the noise parameters changed nothing earlier.** The parameters moved from fixed slots to
   `profile.cho`; all 65 earlier circuits still pass, and no earlier output hash changed (70 circuits now,
   six builds each, three for the density-matrix ones).

## Not done

- Idle noise (T1/T2, gate durations) was added afterwards: `idle-noise.md`, and the profile file takes `coherence` and `time_ns` (below). No crosstalk or non-Pauli two-qubit noise.
- The noise after a gate is always depolarizing; there is no per-gate-type rate (all one-qubit gates share
  a qubit's rate).
- No Toffoli noise (a three-qubit gate has no rate).
- A real device's calibration is read by `scripts/calibration_import.py`: `calibration.md`.
- Rates are rounded to a millionth.


## A read-out scan over a profile: `tools/qscan.cho`

A published calibration's read-out errors can be wrong by a factor (docs/hardware.md: one qubit of `ibm_fez` read 1 six times as often as published). `python3 scripts/hw_spike.py check` measures them, per qubit, in a few seconds:
how often an idle qubit reads 1 (`idle_reads_1`, `p01`) and how often one prepared in 1 reads 0 (`after_x_reads_0`, `p10`). `qscan` turns that file into `readerr` operations:

```
(echo qubits 60 61 62; cat docs/data/hardware/<device>-<time>-readout.json) | qscan      # the circuit's qubits 0, 1, 2 are the device's 60, 61, 62
readerr 0 183000 1000000 21000 1000000
...
```

Put them after the operations of `qprofile` and before the circuit's gates: a later `readerr` replaces that qubit's read-out error, so the scan overrides the calibration for the qubits it measured and nothing else.
Without the `qubits` line the scan's keys are used as they are (each below 20). Probabilities are rounded to 10^-6, half to even, as `qprofile` does. Reference: `scripts/scan_ops.py`; `python3 scripts/check_scan.py`
compares them on 500 random scans and 13 broken inputs (both refuse; the tool exits 2) and runs `qsim` on the output (a qubit given p01 = 0.2 read 1 in 792 of 4000 idle shots).
Authority: heap and standard input and output only. Not shown: that the scan's numbers are better than the calibration's; that is `scripts/hw_scan_model.py` on a run (issue #12, part A).
