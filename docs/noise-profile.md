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

**The profile file.** `scripts/noise_profile.py` reads a JSON file and prints these operations (and, given
a circuit, the circuit with them inserted after its header). `qsim` itself still reads only standard
input and touches no file, which `cancho authority` confirms.

```json
{"qubits": 5,
 "gate1":   {"default": 0.0004, "per_qubit": {"0": 0.0002, "3": 0.0011}},
 "gate2":   {"default": 0.008,  "per_pair":  {"0-1": 0.006, "1-2": 0.011, "3-4": 0.014}},
 "readout": {"default": [0.01, 0.03], "per_qubit": {"4": [0.02, 0.07]}}}
```

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

- No idle noise, T1/T2 decoherence, gate-duration dependence, crosstalk or non-Pauli two-qubit noise.
- The noise after a gate is always depolarizing; there is no per-gate-type rate (all one-qubit gates share
  a qubit's rate).
- No Toffoli noise (a three-qubit gate has no rate).
- No real device's calibration has been used; reading one is not built.
- Rates are rounded to a millionth.
