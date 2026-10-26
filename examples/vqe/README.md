# A variational quantum eigensolver in cancho

The ground state energy of a transverse-field Ising chain of four qubits,

    H = - Z0 Z1 - Z1 Z2 - Z2 Z3 - (X0 + X1 + X2 + X3)        (the critical field)

found the way a quantum computer would be asked to: prepare a parametrised state, measure its energy, change the parameters, repeat. Here the "measurement" is exact (the state vector of
`qsim`'s own `gates`), and the optimiser is [cancho-opt](https://github.com/alpibrusl/cancho-opt)'s `opt minimize` (Nelder-Mead). Three small programs:

| program | does |
|---|---|
| `model.cho` | the Hamiltonian, the ansatz, the energy, and the exact ground state energy by Jacobi eigenvalue rotations on the 16 x 16 matrix |
| `energy.cho` → `vqe-energy` | the objective: angles on standard input, the energy on standard output. **No capability beyond standard input and output** (`cancho authority` says so: no file, no network, no heap, no other program) |
| `vqe.cho` → `vqe` | starts `opt minimize` on `vqe-energy` (4 times, each from where the last stopped) and prints the result next to the exact energy |

The ansatz: `L` times (Ry on every qubit, then CX down the chain), then one more Ry layer: 4 (L + 1) angles.

```
C=cancho
$C build src/complex.cho src/gates.cho src/state.cho examples/vqe/model.cho examples/vqe/energy.cho --std -o vqe-energy
$C build src/complex.cho src/gates.cho src/state.cho examples/vqe/model.cho examples/vqe/vqe.cho    --std -o vqe
./vqe --layers 3 --opt path/to/opt --energy ./vqe-energy
{"layers":3,"parameters":16,"exact":-4.7587704831436435,"energy":-4.758770483143627,"error":1.687538997430238e-14,"evaluations":77592,"restarts":4,"converged":true}
```

## Results **[measured]** (`scripts/check_vqe.py`, one machine, debug compiler build)

| layers | angles | energy found | error against exact | evaluations | time |
|---|---|---|---|---|---|
| 1 | 8 | -4.7342308483 | 2.45e-2 | 2,816 | 4 s |
| 2 | 12 | -4.7586690381 | 1.01e-4 | 24,462 | 33 s |
| 3 | 16 | -4.7587704831 | 1.7e-14 | 77,592 | 110 s |
| 4 | 20 | -4.7587704831 | 6e-15 | 9,851 | 14 s |

* **The first two rows are limits of the ansatz, not of the optimiser.** The lowest energy that ansatz can reach, found independently as the best of 30 BFGS runs from random starts (scipy), is -4.7342308483 and
  -4.7586690381: `vqe` agrees to 1e-11 in both. With 3 layers the ansatz contains the ground state and `vqe` finds it.
* **Why CX and not CZ.** The first version used CZ down the chain. With CZ the ansatz saturates: 2 layers reach -4.73423085, 3 layers reach the same number, 0.0245 above the exact energy (best of 30 BFGS runs
  each; `check_vqe.py` asserts it). The cause was not examined further; the example changed to CX, where 3 layers reach the exact energy.
* **One run of Nelder-Mead is not enough in 12 or more dimensions.** A single run with 12 angles stopped at -4.757557 and reported `converged`: it had not reached the minimum of its ansatz, -4.758669, which
  restarting from where it stopped (4 times) reaches. Nelder-Mead can stall on a point that is not a minimum; restarting is the usual remedy, and it is not free (the 16-angle case took 77,592 evaluations).
* **What would be better:** a gradient method. For rotation gates the gradient of the energy is exact from two more evaluations per angle (the parameter-shift rule), so a BFGS in cancho-opt with a
  gradient protocol would need far fewer evaluations than 77,592. That is not built; `cancho-opt` has only Nelder-Mead.

## Checks

`CANCHO=... OPT=... python3 scripts/check_vqe.py [--long]` (`--long` adds the 3-layer run, about two minutes):

* `vqe-energy` at 300 random angle vectors equals an independent numpy implementation to 2.2e-15, and is never below the exact ground state energy (the variational principle);
* the exact energy `vqe` prints equals numpy's `eigvalsh` to 1.5e-14;
* `vqe-energy` refuses 3 angles, words, `nan` and an infinity;
* the runs above agree with scipy's best BFGS minimum for the same ansatz;
* six deliberate bugs in `model.cho` (CX as CZ, the sign of the field, of the ZZ term, the factor 2 in the X term, the sign of the matrix diagonal, the Jacobi rotation) are each caught.

## What this is not

Not a chemistry example: the Hamiltonian is a spin chain chosen because its exact answer is cheap to compute and check. Not noisy: the energy is exact, with no shot noise and no device noise; running it against `qsim`'s
noise models (or a device, through the `Qpu` budget of `docs/qpu.md`) is the natural next step, and then the energy is a statistic and Nelder-Mead's tolerance is a different question.
