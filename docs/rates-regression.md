# Gate error rates by regression (`ml fit --model linear`), tested with known answers

**Status (2026-10-26): tested on simulated circuits only; not run on a device.** Tags: **[measured]** printed by `scripts/rates_sim.py`, **[choice]**, **[open]**.

## The question

The fits of `docs/hardware.md` run the density-matrix simulator inside an optimiser. Is there a cheaper way to learn a device's gate error rates from circuits run just before a job, with
the tools of the project's own ecosystem? To first order a mirror circuit's survival S (the chance of reading all zeros) is a product over its gates, `S = c * prod (1 - lambda_g)^n_g`
with `n_g` the number of gates of each kind (a `cz` on a given pair, the one-qubit gates of a given qubit) and `c` the read-out. So `log S` is **linear in the gate counts**, and
[cancho-ml](https://github.com/alpibrusl/cancho-ml)'s `ml fit --model linear --l2 ...` on a CSV of counts and `log S` estimates every `lambda_g`; `lambda` is turned into the depolarizing
probability `p` by `lambda = 2p/3` (one qubit) and `4p/5` (two qubits), which is what `qsim`'s channels do to a survival (a depolarized qubit can still read 0) **[choice]**.

## The test: `scripts/rates_sim.py` **[measured]**

A 5-qubit line with known rates (one-qubit p of 3e-4 to 8e-4 per qubit; `cz` p of 4e-3 to 1.5e-2 per pair; read-out 0.8 to 4% and 1.8 to 4%). Random mirror circuits (1 to 12 layers of `sx`/`x`
on a random 70% of the qubits and `cz` on random neighbouring pairs, then the inverse) are run on `qsim`'s exact density matrix and the survival is read with the read-out error. Optionally `--shots 2000` makes
the survival a sample, as a device returns it. 300 circuits, `ml` built from cancho-ml at its pinned compiler (`0207556`, built from source), `--l2 0.001`.
Mean relative error of the estimated p over the four pairs and over the five qubits, three seeds each:

| design | two-qubit rates | one-qubit rates |
|---|---|---|
| exact survival | 10.2%, 7.2%, 5.8% | 72%, 60%, 59% |
| 2000 shots | 9.5%, 10.0%, 18.9% | 131%, 183%, 105% |
| 2000 shots, a third of the circuits with one-qubit gates only (10 to 60 layers, no `cz`) | 8.3%, 7.8%, 10.0% | 38%, 30%, 31% |
| exact survival, same one-qubit-only circuits | 13.8%, 9.9%, 8.4% | 34%, 28%, 25% |
| exact survival, one-qubit rates ten times larger | 21.9%, 13.7%, 7.9% | 17%, 19%, 20% |

- **The two-qubit rates, which dominate the error, are recovered to about 10%**, with shot noise, from 300 circuits.
- **The one-qubit rates are not, at realistic sizes**, unless the circuits include one-qubit-only sequences long enough for them to show; then to about 30%. The read-out intercept comes back right (-0.071 against
  -0.076 true, in the exact run).
- **A first run had every qubit with the same count of one-qubit gates in every circuit** (each layer put a gate on every qubit), so their rates could not be told apart and the estimates were all the same number. The
  design now leaves a random third of the qubits out of each layer; the table is for that design. A device run needs the same care.
- The first-order picture has systematic error of its own (a gate error that a later gate undoes, errors that a mirror circuit makes visible only sometimes): the relative errors above are not all sampling noise,
  and were not separated from it.

## Not shown

Nothing here has run on hardware, and the circuits have no `rz` (on a device it is virtual and free; in `qsim` it would be charged noise, so it was left out). Whether the rates the regression finds on a real
device *predict* its other circuits better than the calibration is the experiment this prepares: about 300 circuits of a few seconds' device time. A second question the test does not answer is
whether the model class (independent depolarizing per gate) is right: `docs/hardware.md` found one qubit's read-out, not a gate rate, to be most of fez's error, and a regression on gate counts alone cannot
see that. The read-out is better measured by the scan of `hw_spike.py check`.

## Building the tools **[measured]**

`ml` (cancho-ml) is built with the compiler it pins, `0207556`: `cargo build --release -p cancho` there (1.5 minutes), `cancho install`, `cancho build --bin ml` (40 seconds). `stats` (cancho-stats) pins a different
compiler, `a4572ea`. Neither builds with the compiler this repository uses, and each refuses to build with another (`this project was written for cancho ...`).
