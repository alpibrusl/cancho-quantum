# QAOA for MaxCut in cancho

The Quantum Approximate Optimisation Algorithm (Farhi, Goldstone, Gutmann 2014) on the simulator of this repository, with [cancho-opt](https://github.com/alpibrusl/cancho-opt)'s `opt minimize` as the optimiser: BFGS with an exact gradient,
Nelder-Mead, or SPSA. The problem is MaxCut on the triangular prism (six vertices, nine edges: two triangles `0-1-2` and `3-4-5` joined by `0-3`, `1-4`, `2-5`). Each triangle loses at least one edge, so the best cut has **7 of
the 9** edges (`qaoa` prints the brute-force value, not a constant). Five small programs, like `examples/vqe`:

| file | what it is |
|---|---|
| `model.cho` | the graph, the circuit (`H` on every qubit, then per layer `RZZ(gamma)` on every edge and `RX(2 beta)` on every qubit), the expected cut, the gradient, the sampled cost |
| `energy.cho` → `qaoa-energy` | angles on standard input (`gamma_1 beta_1 gamma_2 beta_2 ...`, 1 to 4 layers), the cost on standard output: **minus the expected number of cut edges**. No capability beyond standard input and output |
| `gradient.cho` → `qaoa-gradient` | the cost and then its gradient, by the parameter-shift rule over every gate instance (exact, below) |
| `sampled.cho` → `qaoa-sampled` | the cost as a device gives it: minus the mean cut of `--shots S` sampled bit strings, with `--seed K` and `--readout P` |
| `qaoa.cho` → `qaoa` | the driver: starts `opt` from up to 8 fixed points, keeps the best, and prints the exact expected cut at the angles it found next to the best cut |

```
cancho build src/complex.cho src/gates.cho src/measure.cho src/profile.cho src/state.cho examples/qaoa/model.cho examples/qaoa/energy.cho --std -o qaoa-energy     # and gradient.cho, sampled.cho, qaoa.cho
qaoa --layers 3 --opt PATH/opt
{"method":"bfgs","layers":3,"best_cut":7,"expected_cut":6.878022071...,"ratio":0.98257...,"angles":[...],"starts":6,"evaluations":254,"gradients":254,"shots":0}
```

## Results **[measured]** (`scripts/check_qaoa.py`, `scripts/qaoa_study.py`, one machine, debug compiler build)

Exact cost, BFGS with the exact gradient, 6 starts. The optimum is the best of 40 BFGS runs of scipy on an independent numpy implementation; `qaoa` agrees with it to 1e-9 or better.

| layers | angles | expected cut | ratio to the best cut (7) | gradients | time |
|---|---|---|---|---|---|
| 1 | 2 | 5.9392 | 0.8485 | 73 | 0.2 s |
| 2 | 4 | 6.6029 | 0.9433 | 146 | 0.5 s |
| 3 | 6 | 6.8780 | 0.9826 | 254 | 1.2 s |
| 4 | 8 | 6.9903 | 0.9986 | 361 | 2.4 s |

The ratio rises with every layer, as the algorithm promises, and 4 layers are 0.0097 of a cut from the best. A random bit string cuts 4.5 (ratio 0.643): the cost at all-zero angles.

**With shots** (2 layers, 6 starts, seeds 1 to 5; `ratio` is the *exact* expected cut at the angles found, not what the optimiser saw; the exact optimum is 0.9433):

| method | shots per evaluation | read-out error | median ratio | worst ratio | median shots spent |
|---|---|---|---|---|---|
| SPSA, 200 iterations | 100 | 0 | 0.9416 | 0.9073 | 240,600 |
| SPSA, 200 iterations | 1000 | 0 | 0.9412 | 0.9404 | 2,406,000 |
| SPSA, 200 iterations | 1000 | 0.05 | 0.9417 | 0.9407 | 2,406,000 |
| Nelder-Mead | 100 | 0 | 0.9087 | 0.8919 | 890,700 |
| Nelder-Mead | 1000 | 0 | 0.9145 | 0.9127 | 8,905,000 |
| Nelder-Mead | 1000 | 0.05 | 0.9336 | 0.9075 | 10,493,000 |

* **SPSA gets within 0.002 of the exact optimum from 100 shots per evaluation**, with 240,000 shots in all; Nelder-Mead stops at 0.91 with about four times as many. (BFGS has no gradient to use here: `qaoa-sampled` prints a value only, and `qaoa` refuses `--method bfgs --shots`.) The SPSA gains `a = 0.3`, `c = 0.2` are the ones tuned for the VQE example (`examples/vqe/README.md`), not tuned again.
* **A read-out error does not move the optimum here.** With every bit flipped independently with probability `P`, the expected cut becomes `r E + (1 - 2 r) cut` with `r = 2 P (1 - P)` (E the number of edges): an affine function of the cut, so the same angles maximise it. `check_qaoa.py` verifies the formula on 300 seeds (P = 0.08: 5.979 against the predicted 5.981). In the VQE the error scales two different terms differently, which is why mitigation mattered there and does not here.
* One graph, one machine, five seeds. The worst SPSA ratio at 100 shots, 0.9073, is a run that stopped in a worse local minimum; with more starts it would not be.

## Checks

`CANCHO=... OPT=... python3 scripts/check_qaoa.py [--mutants]`:

* `qaoa-energy` at 300 random angle vectors equals an independent numpy QAOA (built from the circuit's matrices, a different code path) to 1.8e-14, and is never below minus the best cut;
* `qaoa-gradient` equals central differences of numpy's cost to 4e-9 (gate 1e-7), and its first number is the cost;
* `qaoa-sampled` over 400 seeds is unbiased (0.9 standard errors) with the predicted spread (0.996 of `sqrt(Var(cut) / S)`), has the predicted read-out mean, is a function of the angles and the seed, and 600 random runs never fail or trap;
* the objectives and the driver refuse what they should (no angles, one, three or ten, a word, `nan`, an overflow, `--layers 5`, `--starts 9`, BFGS with shots), each with status 2 and nothing on standard output;
* `qaoa` reaches scipy's optimum for 1 to 4 layers, prints the brute-force best cut, and the SPSA and Nelder-Mead runs with shots spend the shots they say;
* `--mutants`: nine deliberate bugs in the model (the sign of gamma, the factor 2 of the mixer, a self-loop edge, a wrong edge end, the factor 2 of `d/d beta`, the shift rule of the mixer, the sum over the edges in `d/d gamma`, the imaginary parts left out of the probabilities, a qubit missing from the Hadamards) are each caught.

## What this is not

A graph this size is solved by looking at 64 bit strings; the point is the machinery (an exact gradient for a circuit whose angle appears in nine gates, an optimiser that needs no gradient on sampled costs, an independent reference), not an advantage. The circuit is the textbook one with no transpilation, so a run on a device would add the routing and the gate noise the VQE example also leaves out.
