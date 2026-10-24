# A real device's calibration

> **Status: built and measured.** Qiskit 2.6.1, qiskit-aer 0.17, qiskit-ibm-runtime fake
> backend `perth`. Checked by `scripts/check_calibration.py`.

## What it is, and what it is not

`profiles/ibm_perth_2024-05-27.json` is the calibration IBM published for the 7-qubit
`ibm_perth` on **2024-05-27**, converted into a noise profile by
`tools/qcalib.cho`. The numbers are IBM's, taken from the properties snapshot
that ships inside the `qiskit-ibm-runtime` package (its "fake backends"). Nothing was
fetched from a live machine, no account was used, and this project measured nothing. One
snapshot of one retired-class device from 2024 says little about any machine today; it is
a real, complete set of numbers of the right size, which the earlier example profile was not
(that one is invented).

## The conversions (the part to check)

| Published | Becomes |
|---|---|
| `prob_meas1_prep0`, `prob_meas0_prep1` | `readerr` p01, p10, as published |
| `T1`, `T2` (us) | `coher`, in ns; T2 above 2 T1 would be clipped to 2 T1 (none was, for this device) |
| `sx` `gate_length` per qubit | `dur1` |
| `cx` `gate_length` per pair | `dur2`, the mean of the two directions (they differ by up to 36 ns here) |
| `sx` `gate_error` per qubit | `gate1err` = 3/2 (r - r_relax), at least 0 |
| `cx` `gate_error` per pair | `gate2err` = 5/4 (r - r_relax), at least 0; r is the mean of the two directions |

`gate_error` is the average gate infidelity from randomized benchmarking, and it already
includes the decay during the gate. `qsim` adds that decay itself, so r_relax, the average
infidelity of the idle channel for the gate's duration, is subtracted first. Without that
the decay would be counted twice. The factors 3/2 and 5/4 turn an average infidelity into
the depolarizing probability `qsim` applies (a one-qubit depolarizing channel with
probability p has average infidelity 2p/3; the two-qubit one 4p/5).

Every one-qubit gate of a circuit gets the qubit's `sx` rate, as if it were one `sx`: a
real `h` is three native operations and `rz` is free, so a cancho circuit of `h` and `rz`
is noisier or quieter than the compiled one would be. The comparison below uses only
native gates for that reason.

## Measured

1. **Provenance.** 54 numbers in the profile (readout, T1, T2, gate times, 13 depolarizing
   rates) were re-derived from the raw snapshot with Qiskit Aer's own thermal-relaxation
   channel and Qiskit's `average_gate_fidelity`, a different route from the importer's
   NumPy one: the rates agree to 8e-16 and the times to a nanosecond.
2. **Behaviour against Aer.** Two circuits of native gates (13 and 11 gates; `x`, `sx` as
   `rx 1/2`, `cx`) on 7 qubits, run on the density matrix through the profile and in Aer
   with `NoiseModel.from_backend` on the same snapshot: trace distance **9.3e-4 and
   9.6e-4**. The noise itself moves the state by 0.079 and 0.069, so the residual is
   about 1% of the effect.
3. **The check can fail.** Leaving the idle decay out gives 5.4e-2 and 3.7e-2; using the
   published error as the depolarizing rate without taking the decay out gives 2.6e-2 and
   2.3e-2. Both are 24 to 58 times worse than the profile.
4. **A finding.** For 2 of the 6 pairs (0-1 and 1-2) the decay computed from T1, T2 and the
   `cx` length alone is *larger* than the published `cx` error (0.0071 against 0.0069 and
   0.0109 against 0.0079). The depolarizing part is then 0, so those pairs are modelled with
   more error than IBM reports. T1 and T2 are measured at one time and the benchmark at
   another, and the `cx` duration is not the whole story, so the three need not be
   consistent. Aer clips the same way.

## Not done

- One snapshot. No other device, no fetching a current calibration.
- The residual of 1e-3 is not explained piece by piece. Candidates: the order of the
  depolarizing and decay steps, the mean of two `cx` directions, times rounded to the
  nanosecond. Each is below the effect it is compared to; none was isolated.
- Readout error is copied from the file and not re-checked against Aer here (the
  readout machinery is checked as a binomial in `check_noise.py`).
- Crosstalk, leakage, and coherent errors are not in a calibration and are not modelled.
- No Toffoli rate, and no `rz`/`h` decomposition (see above).
