# A variational quantum eigensolver in cancho

The ground state energy of a transverse-field Ising chain of four qubits,

    H = - Z0 Z1 - Z1 Z2 - Z2 Z3 - (X0 + X1 + X2 + X3)        (the critical field)

found the way a quantum computer would be asked to: prepare a parametrised state, measure its energy, change the parameters, repeat. Here the "measurement" is exact (the state vector of
`qsim`'s own `gates`), and the optimiser is [cancho-opt](https://github.com/alpibrusl/cancho-opt)'s `opt minimize`: BFGS with the exact parameter-shift gradient (the default), or Nelder-Mead. Four small programs:

| program | does |
|---|---|
| `model.cho` | the Hamiltonian, the ansatz, the energy, and the exact ground state energy by Jacobi eigenvalue rotations on the 16 x 16 matrix |
| `gradient.cho` → `vqe-gradient` | the objective for BFGS: the energy and then its gradient by the parameter-shift rule (exact: each angle is that of an Ry, so dE/dθ = (E(θ + π/2) − E(θ − π/2)) / 2). Same capabilities: none beyond standard input and output |
| `energy.cho` → `vqe-energy` | the objective for Nelder-Mead: angles on standard input, the energy on standard output. **No capability beyond standard input and output** (`cancho authority` says so: no file, no network, no heap, no other program) |
| `vqe.cho` → `vqe` | starts `opt minimize --method bfgs` on `vqe-gradient` (once), or with `--method nelder-mead` on `vqe-energy` (4 times, each from where the last stopped), and prints the result next to the exact energy |

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

`CANCHO=... OPT=... python3 scripts/check_vqe.py [--long]` (`--long` adds the 3-layer Nelder-Mead run, about two minutes; `OPT` is a cancho-opt build with `--method bfgs`):

* `vqe-energy` at 300 random angle vectors equals an independent numpy implementation to 2.2e-15, and is never below the exact ground state energy (the variational principle);
* `vqe-gradient` at 60 random angle vectors equals numpy's own parameter-shift gradient to 3e-15 and central finite differences of the energy to 1e-9;
* the exact energy `vqe` prints equals numpy's `eigvalsh` to 1.5e-14;
* `vqe-energy` and `vqe-gradient` refuse 3 angles, words, `nan` and an infinity;
* the runs above agree with scipy's best BFGS minimum for the same ansatz, and the 3- and 4-layer BFGS runs reach the exact energy to 1e-9;
* eleven deliberate bugs in `model.cho` are each caught: CX as CZ, the sign of the field, of the ZZ term, the factor 2 in the X term, the sign of the matrix diagonal, the Jacobi rotation, and for the gradient the shift (2π/2, π/4), the missing 1/2, its sign, and an angle not put back.

## What this is not

Not a chemistry example: the Hamiltonian is a spin chain chosen because its exact answer is cheap to compute and check. Not noisy: the energy is exact, with no shot noise and no device noise; running it against `qsim`'s
noise models (or a device, through the `Qpu` budget of `docs/qpu.md`) is the natural next step, and then the energy is a statistic and Nelder-Mead's tolerance is a different question.
