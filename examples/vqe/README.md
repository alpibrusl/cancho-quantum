# A variational quantum eigensolver in cancho

The ground state energy of a transverse-field Ising chain of four qubits,

    H = - Z0 Z1 - Z1 Z2 - Z2 Z3 - (X0 + X1 + X2 + X3)        (the critical field)

found the way a quantum computer would be asked to: prepare a parametrised state, measure its energy, change the parameters, repeat. Here the "measurement" is exact (the state vector of
`qsim`'s own `gates`), and the optimiser is [cancho-opt](https://github.com/alpibrusl/cancho-opt)'s `opt minimize`: BFGS with the exact parameter-shift gradient (the default), Nelder-Mead, or SPSA (`--method spsa`, for the sampled energy). Five small programs:

| program | does |
|---|---|
| `model.cho` | the Hamiltonian, the ansatz, the energy, and the exact ground state energy by Jacobi eigenvalue rotations on the 16 x 16 matrix |
| `gradient.cho` → `vqe-gradient` | the objective for BFGS: the energy and then its gradient by the parameter-shift rule (exact: each angle is that of an Ry, so dE/dθ = (E(θ + π/2) − E(θ − π/2)) / 2). Same capabilities: none beyond standard input and output |
| `sampled.cho` → `vqe-sampled` | the objective as a device would give it: the energy (or with `--gradient` the energy and its parameter-shift gradient) **estimated from shots**, with an optional read-out error and its mitigation (below). Reads its arguments, standard input and output: no file, no network, no other program |
| `energy.cho` → `vqe-energy` | the objective for Nelder-Mead: angles on standard input, the energy on standard output. **No capability beyond standard input and output** (`cancho authority` says so: no file, no network, no heap, no other program) |
| `vqe.cho` → `vqe` | starts `opt minimize --method bfgs` on `vqe-gradient` (once), or with `--method nelder-mead` on `vqe-energy` (4 times, each from where the last stopped), and prints the result next to the exact energy; with `--shots S` it uses `vqe-sampled` instead, and also prints the exact energy at the angles it found (`true_energy`) and the shots spent |

The ansatz: `L` times (Ry on every qubit, then CX down the chain), then one more Ry layer: 4 (L + 1) angles.

```
C=cancho
$C build src/complex.cho src/gates.cho src/state.cho examples/vqe/model.cho examples/vqe/energy.cho --std -o vqe-energy
$C build src/complex.cho src/gates.cho src/state.cho examples/vqe/model.cho examples/vqe/gradient.cho --std -o vqe-gradient
$C build src/complex.cho src/gates.cho src/state.cho examples/vqe/model.cho examples/vqe/vqe.cho    --std -o vqe
./vqe --layers 3 --opt path/to/opt --gradient ./vqe-gradient
{"method":"bfgs","layers":3,"parameters":16,"exact":-4.7587704831436435,"energy":-4.758770483143635,"error":8.881784197001252e-15,"evaluations":58,"gradients":58,"restarts":1,"converged":true}
```

## Results **[measured]** (`scripts/check_vqe.py`, one machine, debug compiler build)

| layers | angles | exact energy minus ansatz limit | BFGS: error / gradients / time | Nelder-Mead: error / evaluations / time |
|---|---|---|---|---|
| 1 | 8 | 2.45e-2 (the ansatz cannot do better) | 2.45e-2 / 23 / 0.04 s | 2.45e-2 / 2,816 / 4 s |
| 2 | 12 | 1.01e-4 (same) | 1.01e-4 / 313 / 0.6 s | 1.01e-4 / 24,462 / 33 s |
| 3 | 16 | 0 | 6.6e-14 / 56 / 0.1 s | 1.7e-14 / 77,592 / 110 s |
| 4 | 20 | 0 | 5e-13 / 37 / 0.08 s | 6e-15 / 9,851 / 14 s |

A BFGS gradient costs 2 P + 1 energy evaluations (P angles; 33 for 16 angles), so the 3-layer run is about 1,850 energy evaluations against Nelder-Mead's 77,592 (on a device, 2 P circuits per gradient). The 1- and 2-layer errors are
the **limits of the ansatz, not of the optimiser**: the lowest energy that ansatz can reach, found independently as the best of 30 scipy BFGS runs from random starts, is -4.7342308483 and -4.7586690381, and both methods agree
with it to 1e-11. With 3 layers the ansatz contains the ground state and both find it.

* **Why CX and not CZ.** The first version used CZ down the chain. With CZ the ansatz saturates: 2 layers reach -4.73423085, 3 layers reach the same number, 0.0245 above the exact energy (best of 30 scipy BFGS runs
  each; `check_vqe.py` asserts it). The cause was not examined further; the example changed to CX, where 3 layers reach the exact energy.
* **One run of Nelder-Mead is not enough in 12 or more dimensions.** A single run with 12 angles stopped at -4.757557 and reported `converged`: it had not reached the minimum of its ansatz, -4.758669, which
  restarting from where it stopped (4 times) reaches. Nelder-Mead can stall on a point that is not a minimum; restarting is the usual remedy, and it is not free.
* **BFGS needs one run, and a gradient tolerance it can meet.** With `gtol` 1e-8 the 2-layer run stops at a gradient of 2e-8 with "precision loss" (the energy's own rounding, about 1e-15, sets how well a gradient can be
  resolved), still at the ansatz's minimum; `vqe` uses 1e-6, which is met.
* **Corrected in place.** This README said a gradient method "would need far fewer evaluations than 77,592" and that it was not built; it is built (cancho-opt `--method bfgs`) and the table is the measurement.

## Checks

`CANCHO=... OPT=... python3 scripts/check_vqe.py [--long]` (`--long` adds the 3-layer Nelder-Mead run, about two minutes; `OPT` is a cancho-opt build with `--method bfgs` and `--method spsa`):

* `vqe-energy` at 300 random angle vectors equals an independent numpy implementation to 2.2e-15, and is never below the exact ground state energy (the variational principle);
* `vqe-gradient` at 60 random angle vectors equals numpy's own parameter-shift gradient to 3e-15 and central finite differences of the energy to 1e-9;
* the exact energy `vqe` prints equals numpy's `eigvalsh` to 1.5e-14;
* `vqe-energy` and `vqe-gradient` refuse 3 angles, words, `nan` and an infinity;
* SPSA reaches an error below 0.05 on the exact energy (800 iterations) and below 0.15 sampled with 1,000 shots (200 iterations), on seeds 1 to 3, with `evaluations = 2 nit + 1` and the shots as counted;
* the runs above agree with scipy's best BFGS minimum for the same ansatz, and the 3- and 4-layer BFGS runs reach the exact energy to 1e-9;
* eighteen deliberate bugs in `model.cho` are each caught (eleven here, seven in the sampling code, below): CX as CZ, the sign of the field, of the ZZ term, the factor 2 in the X term, the sign of the matrix diagonal, the Jacobi rotation, and for the gradient the shift (2π/2, π/4), the missing 1/2, its sign, and an angle not put back.

## What this is not

Not a chemistry example: the Hamiltonian is a spin chain chosen because its exact answer is cheap to compute and check. Not noisy: the energy is exact, with no shot noise and no device noise; running it against `qsim`'s
noise models (or a device, through the `Qpu` budget of `docs/qpu.md`) is the natural next step, and then the energy is a statistic and Nelder-Mead's tolerance is a different question.

## Sampling: shots, read-out error and mitigation

The energy above is exact, which a device never gives. `vqe-sampled` estimates it the way a device would: the ansatz state is prepared, then measured `S` times in the Z basis (one circuit, which gives every `Z Z` term) and `S`
times after a Hadamard on every qubit (the second circuit, which gives every `X` term), so an energy costs `2 S` shots; the estimate is `E = - sum <Z_q Z_(q+1)> - h sum <X_q>` with each expectation the mean of the sampled
products. `vqe --shots S` runs the optimisers on it. Choices:

* The samples come from `qsim`'s own sampler (`measure.sample`), seeded. The seed is a function of the angles and of `--seed` (FNV-1a over the bits of the angles), so the objective is a *function* of the angles, as the optimisers
  assume: the same angles and seed give the same samples, different angles independent-looking ones.
* `--readout P` flips each measured bit with probability `P` (the sampler's own read-out error). With symmetric flips `<Z Z>` is scaled by `(1 - 2 P)^2` and `<X>` by `(1 - 2 P)`, so the estimate is biased unless `--mitigate`
  divides by those factors (the correction `qmitigate` makes for counts, here for expectations).
* Not modelled: gate noise, correlated or asymmetric read-out error, drift.

### What was measured (`scripts/check_vqe.py`, `scripts/vqe_noise_study.py`)

**The estimator** (400 seeds, 256 shots per basis, one random angle vector): the mean is -1.1465 against the exact -1.1428 (0.6 standard errors of the mean), and the spread is 0.982 of the predicted
`sqrt((Var_Z + h^2 Var_X) / S)` = 0.1226, where the variances are those of the observables in the state, computed by numpy. **Read-out error 0.05** (300 seeds, 1,024 shots): the unmitigated mean, -0.9512, is the
predicted `-E_ZZ (1-2P)^2 - E_X (1-2P)` = -0.9535 (0.6 se), 0.19 above the exact energy; mitigated, -1.1398 is the exact energy (0.7 se). The sampled parameter-shift gradient, over 200 seeds, has every component's
mean within 2.2 standard errors of the exact gradient. Seven deliberate bugs in the sampling code (the mean over shots + 1, the mitigation factor, the sign of the X term, a missing Hadamard, a seed that ignores the angles, the
scale of the read-out probability, an X estimate without its sign) are each caught.

**Found by the check:** the first version of the seed mixing used a checked `+` that overflowed for about 8 percent of angle vectors, and the program **trapped** on them. It uses `wrapping_add` now, and the check runs 600 random
angle vectors, shot counts and seeds and requires no failure.

**The optimisers on it** (3 layers, 16 angles, seeds 1 to 5; `true error` is the *exact* energy at the angles found minus the ground state energy, `reported` is what the optimiser saw; the same seeds give the same table):

| method | shots per basis | read-out error | mitigated | median true error | worst true error | median reported - exact | median shots spent | converged |
|---|---|---|---|---|---|---|---|---|
| BFGS | 100 | 0 | no | 0.327 | 0.731 | -0.001 | 224,400 | 0 of 5 |
| BFGS | 1000 | 0 | no | 0.063 | 0.101 | -0.031 | 2,046,000 | 0 of 5 |
| BFGS | 4096 | 0 | no | 0.043 | 0.048 | -0.005 | 6,488,064 | 0 of 5 |
| BFGS | 1000 | 0.03 | no | 0.064 | 0.124 | +0.299 | 2,706,000 | 0 of 5 |
| BFGS | 1000 | 0.03 | yes | 0.057 | 0.070 | -0.073 | 2,442,000 | 0 of 5 |
| Nelder-Mead | 100 | 0 | no | 0.731 | 0.756 | -0.241 | 800,000 | 0 of 5 |
| Nelder-Mead | 1000 | 0 | no | 0.160 | 0.229 | -0.083 | 8,000,000 | 0 of 5 |
| Nelder-Mead | 4096 | 0 | no | 0.088 | 0.092 | -0.048 | 32,768,000 | 0 of 5 |
| Nelder-Mead | 1000 | 0.03 | no | 0.180 | 0.240 | +0.261 | 8,000,000 | 0 of 5 |
| Nelder-Mead | 1000 | 0.03 | yes | 0.214 | 0.434 | -0.078 | 8,000,000 | 0 of 5 |
| SPSA, 200 iterations | 100 | 0.0 | no | 0.122 | 0.196 | +0.099 | 80,200 | 5 of 5 (completed) |
| SPSA, 200 iterations | 1000 | 0.0 | no | 0.056 | 0.077 | +0.063 | 802,000 | 5 of 5 (completed) |
| SPSA, 200 iterations | 4096 | 0.0 | no | 0.041 | 0.076 | +0.029 | 3,284,992 | 5 of 5 (completed) |
| SPSA, 200 iterations | 1000 | 0.03 | no | 0.055 | 0.076 | +0.409 | 802,000 | 5 of 5 (completed) |
| SPSA, 200 iterations | 1000 | 0.03 | yes | 0.059 | 0.094 | +0.049 | 802,000 | 5 of 5 (completed) |
| SPSA, 800 iterations | 100 | 0.0 | no | 0.084 | 0.137 | +0.059 | 320,200 | 5 of 5 (completed) |
| SPSA, 800 iterations | 1000 | 0.0 | no | 0.034 | 0.047 | +0.085 | 3,202,000 | 5 of 5 (completed) |
| SPSA, 800 iterations | 4096 | 0.0 | no | 0.033 | 0.037 | +0.053 | 13,115,392 | 5 of 5 (completed) |
| SPSA, 800 iterations | 1000 | 0.03 | no | 0.042 | 0.059 | +0.367 | 3,202,000 | 5 of 5 (completed) |
| SPSA, 800 iterations | 1000 | 0.03 | yes | 0.037 | 0.052 | -0.042 | 3,202,000 | 5 of 5 (completed) |

* **SPSA** (`opt minimize --method spsa`, cancho-opt section 11: two objective evaluations per iteration whatever the number of angles; 200 or 800 iterations, `--a 0.3 --c 0.2`, picked on seeds 101 to 104 so that they are not the table's seeds)
  "completes" its iterations (it has no convergence test, so the last column is not comparable to the others). At 100 shots it is the clear winner (true error 0.12 and 0.08 against BFGS's 0.33); at 1,000 shots 200 iterations
  already match BFGS (0.056 against 0.063) with 2.5 times fewer shots (802,000 against 2,046,000), and 800 iterations are better (0.034) for more (3.2 million); at 4,096 shots 200 iterations match BFGS (0.041 against 0.043) with half the shots.
  Its error stops falling with the shots: 800 iterations give 0.034 and 0.033 at 1,000 and 4,096 shots, and **with the exact energy (no shot noise) the same 800 iterations still stop at 0.027 to 0.036** (`scripts/check_vqe.py`), where BFGS
  reaches 1e-9. So SPSA's floor here is its own, not shot noise, and it is **not a floor**: it is the step gain `a = 0.3` over 800 iterations ("The gain schedule", below).
  Its reported energy is one fresh evaluation at the final angles, not the best of many noisy ones, so it is not optimistic: it lies *above* the exact energy (+0.03 to +0.1) in every row without read-out error.
* **BFGS is better than Nelder-Mead at every setting**, in the true error (about 2 to 3 times smaller) and in the shots (about 3 to 5 times fewer). Neither converges: BFGS stops on "precision loss" (the gradient noise puts a floor under
  what the line search can resolve), Nelder-Mead at its 4,000-evaluation limit. The error does not fall as `1/sqrt(S)` from 1,000 to 4,096 shots (0.063 to 0.043, where 0.031 would be that law); why was not examined.
* **The reported energy is not to be trusted, in both directions.** Noise makes it optimistic: minimising a noisy objective picks the angles where the noise happened to be low, so it can lie *below* the exact ground state energy
  (Nelder-Mead at 100 shots: -0.24, a violation of the variational principle that no exact energy could show), while the true energy at those angles is always above it. A read-out error makes it pessimistic (+0.3) unless mitigated.
* **Mitigation changes the number you quote, not where the optimum is:** the true error is about the same with and without it (0.064 and 0.057 for BFGS), since the read-out error scales the landscape without moving its minimum
  much, but the reported energy is 0.3 off without it and 0.07 off with it (it inflates the variance by `1 / (1 - 2 P)^2`, so it is noisier).
* One machine, one seed set, one ansatz; the shots counted are `runs x (1 + 2 P) x 2 S` for BFGS (one run per distinct point) and `runs x 2 S` for Nelder-Mead and SPSA (`2 nit + 1` runs).

### The gain schedule (SPSA) **[measured, `scripts/spsa_gain_study.py`]**

The 0.03 above the ground state that SPSA stops at with no shot noise at all was reported here as "its floor", cause "probably the gain schedule". Measured now (3 layers, 16 angles from 0.3, `opt minimize --method spsa` on the exact energy, seeds 1 to 5; error = energy found minus the exact ground state energy):

**Table 1: 800 iterations, A = 80.**

| a | c | median error | worst error |
|---|---|---|---|
| 0.1 | 0.2 | 0.0487 | 0.0660 |
| 0.1 | 0.05 | 0.0470 | 0.0613 |
| 0.1 | 0.01 | 0.0469 | 0.0609 |
| 0.3 | 0.2 | 0.0309 | 0.0368 |
| 0.3 | 0.05 | 0.0285 | 0.0334 |
| 0.3 | 0.01 | 0.0284 | 0.0332 |
| 1.0 | 0.2 | 0.0118 | 0.0237 |
| 1.0 | 0.05 | 0.0130 | 0.0164 |
| 1.0 | 0.01 | 0.0129 | 0.0168 |

* **The gain `a` sets it; with `A = 80` the probe size `c` does not.** The error falls with `a` (0.047, 0.029, 0.012) and `c` from 0.2 to 0.01 moves it by 0.002 at most. So the bias of the finite difference (of order `c^2`) is not the cause; the steps are simply too short to get there: `a_k = a / (k + A)^0.602` has summed to too little by iteration 800.
* **With `A = 0` and a large gain it does** (Table 1b, 800 iterations):

| a | c | A | median error | worst error |
|---|---|---|---|---|
| 1.0 | 0.2 | 0 | 0.0313 | 0.0938 |
| 1.0 | 0.05 | 0 | 0.0042 | 0.0272 |
| 1.0 | 0.01 | 0 | 0.0143 | 0.0276 |

  The shortest probe is not the best either (0.014 at `c = 0.01`), so I do not claim a rule; only that "`c` does not matter" is true of Table 1 and false of Table 1b. Why was not examined.

**Table 2: c = 0.05.**

| a | iterations | A | median error | worst error |
|---|---|---|---|---|
| 0.3 | 200 | 0 | 0.0864 | 0.2341 |
| 0.3 | 200 | 80 | 0.0416 | 0.0572 |
| 0.3 | 800 | 0 | 0.0333 | 0.1234 |
| 0.3 | 800 | 80 | 0.0285 | 0.0334 |
| 0.3 | 3000 | 0 | 0.0182 | 0.0950 |
| 0.3 | 3000 | 80 | 0.0213 | 0.0235 |
| 1.0 | 200 | 0 | 0.0954 | 0.1938 |
| 1.0 | 200 | 80 | 0.0353 | 0.1484 |
| 1.0 | 800 | 0 | 0.0042 | 0.0272 |
| 1.0 | 800 | 80 | 0.0130 | 0.0164 |
| 1.0 | 3000 | 0 | 0.0033 | 0.0247 |
| 1.0 | 3000 | 80 | 0.0107 | 0.0129 |
| 3.0 | 200 | 0 | 3.4919 | 4.8848 |
| 3.0 | 200 | 80 | 1.7732 | 2.7141 |
| 3.0 | 800 | 0 | 0.1677 | 0.1897 |
| 3.0 | 800 | 80 | 0.0427 | 0.3159 |
| 3.0 | 3000 | 0 | 0.0050 | 0.0130 |
| 3.0 | 3000 | 80 | 0.0014 | 0.0067 |
| 10.0 | 200 | 0 | 4.3105 | 5.6740 |
| 10.0 | 200 | 80 | 4.8858 | 5.6241 |
| 10.0 | 800 | 0 | 4.7773 | 5.3119 |
| 10.0 | 800 | 80 | 3.5142 | 5.3977 |
| 10.0 | 3000 | 0 | 0.7886 | 1.7520 |
| 10.0 | 3000 | 80 | 2.0033 | 3.0925 |

* **It was never a floor.** With `a = 1` the error is 0.004 at 800 iterations and 0.003 at 3,000 (stability constant A = 0), against BFGS's 1e-9: close, not equal, since SPSA never converges in the sense BFGS does.
* **A larger gain is not free.** `a = 3` is wild early (an error of 1.8 to 3.5 after 200 iterations, where the starting point is 0.73 above) and recovers only by 3,000 iterations; `a = 10` has not recovered by then. A step is `a_k` times `(f+ - f-) / (2 c_k) * delta`, whose components are about the size of the gradient's norm (a few), so with `A = 0` the first step moves every angle by several radians when `a = 3` (a reading of the formula, not measured separately).
* **The stability constant `A` buys early safety with late precision.** With `A = 80` the first steps are shorter (`a = 1`, 200 iterations: 0.035 against 0.095 for `A = 0`, whose worst run is 0.19) and the late ones too (800 iterations: 0.013 against 0.004).

**With shots (Table 3; seeds 101 to 104, the ones the defaults were chosen on; A = iterations / 10; error of the angles found, in the exact energy).**

| a | c | iterations | shots per basis | median true error | worst true error |
|---|---|---|---|---|---|
| 0.3 | 0.2 | 200 | 100 | 0.1042 | 0.2078 |
| 0.3 | 0.2 | 200 | 1000 | 0.0427 | 0.0611 |
| 0.3 | 0.2 | 200 | 4096 | 0.0350 | 0.0435 |
| 0.3 | 0.2 | 800 | 100 | 0.0899 | 0.1128 |
| 0.3 | 0.2 | 800 | 1000 | 0.0318 | 0.0348 |
| 0.3 | 0.2 | 800 | 4096 | 0.0278 | 0.0302 |
| 0.6 | 0.3 | 200 | 100 | 0.1223 | 0.1388 |
| 0.6 | 0.3 | 200 | 1000 | 0.0296 | 0.0533 |
| 0.6 | 0.3 | 200 | 4096 | 0.0297 | 0.0482 |
| 0.6 | 0.3 | 800 | 100 | 0.0704 | 0.1097 |
| 0.6 | 0.3 | 800 | 1000 | 0.0320 | 0.0353 |
| 0.6 | 0.3 | 800 | 4096 | 0.0263 | 0.0284 |
| 1.0 | 0.3 | 200 | 100 | 0.4481 | 0.8367 |
| 1.0 | 0.3 | 200 | 1000 | 0.0912 | 0.1872 |
| 1.0 | 0.3 | 200 | 4096 | 0.0738 | 0.2720 |
| 1.0 | 0.3 | 800 | 100 | 0.1368 | 0.1800 |
| 1.0 | 0.3 | 800 | 1000 | 0.0217 | 0.0270 |
| 1.0 | 0.3 | 800 | 4096 | 0.0226 | 0.0289 |

* **Shot noise changes the answer.** A larger gain helps only with many iterations and enough shots: `a = 1`, `c = 0.3` gives 0.022 at 800 iterations and 1,000 shots against 0.032 for the defaults, but 0.091 at 200 iterations and 0.45 at 200 iterations and 100 shots. The probe size matters with noise (it must be above the noise's scale: in an earlier grid, not kept in the script, at 1,000 shots and 800 iterations, seeds 101 to 104, `c = 0.3` beat `c = 0.1` for each of `a` = 0.3, 1 and 3 and `A` = 80 and 800).
* **So there is no single better default, and the defaults stay** (`a = 0.3`, `c = 0.2`, A a tenth of the iterations): the safe choice for 200 to 800 iterations and 100 to 4,096 shots. `vqe --method spsa --a 1 --c 0.3 --maxiter 800` is better when the shots are 1,000 or more; `--stability` is a flag of `vqe` now (and of `opt`) for the rest. The tables in "What was measured" above use the defaults, and still say what they said.
* One ansatz, one machine, five (or four) seeds; the grids are coarse, and the best cell of each table sits at its edge or next to a cliff, so a finer grid might find more.
