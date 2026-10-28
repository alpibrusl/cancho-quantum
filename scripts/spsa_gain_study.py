#!/usr/bin/env python3
"""Why SPSA stops 0.03 above the ground state of the VQE of examples/vqe when there is no shot noise at all, and what moves it. Prints the two tables of that README's "The gain schedule" section.

    CANCHO=... OPT=... python3 scripts/spsa_gain_study.py

`opt minimize --method spsa` on `vqe-energy` (the exact energy), 3 layers, 16 angles all starting at 0.3, seeds 1 to 5; the number is the energy found minus the exact ground state energy
(median and worst of the five). Table 1 varies the step gain `a` and the probe size `c` at 800 iterations; table 2 the gain, the iterations and the stability constant `A`, with c = 0.05.
Table 3 is the same question with shot noise: `vqe --method spsa --shots S` (seeds 101 to 104, the ones the defaults were tuned on), the error being that of the angles found, in the exact energy.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CANCHO = os.environ.get("CANCHO", "cancho")
OPT = os.environ["OPT"]
EXACT = -4.7587704831436435
X0 = ",".join(["0.3"] * 16)


def build(name="vqe-energy", main="examples/vqe/energy.cho"):
    exe = os.path.join(tempfile.mkdtemp(prefix="gain-"), name)
    files = [os.path.join(ROOT, f) for f in ("src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho", "examples/vqe/model.cho", main)]
    r = subprocess.run([CANCHO, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])
    return exe


def cell(args):
    exe, (a, c, iterations, stability) = args
    errs = []
    for seed in (1, 2, 3, 4, 5):
        r = subprocess.run([OPT, "minimize", "--method", "spsa", "--x0", X0, "--maxiter", str(iterations), "--a", str(a), "--c", str(c), "--stability", str(stability), "--seed", str(seed), "--", exe], capture_output=True, text=True)
        errs.append(json.loads(r.stdout)["fun"] - EXACT)
    return statistics.median(errs), max(errs)


def cell_sampled(args):
    (energy, sampled, driver), ((a, c), iterations, shots) = args
    errs = []
    for seed in (101, 102, 103, 104):
        r = subprocess.run([driver, "--method", "spsa", "--layers", "3", "--opt", OPT, "--energy", energy, "--sampled", sampled, "--shots", str(shots), "--seed", str(seed), "--a", str(a), "--c", str(c),
                            "--maxiter", str(iterations), "--stability", str(iterations // 10)], capture_output=True, text=True)
        errs.append(json.loads(r.stdout)["true_error"])
    return statistics.median(errs), max(errs)


def table(exe, title, header, cfgs, label):
    print(title)
    print(header)
    print("|" + "---|" * (header.count("|") - 1))
    with ThreadPoolExecutor(4) as pool:
        for cfg, (med, worst) in zip(cfgs, pool.map(cell, [(exe, c) for c in cfgs])):
            print(label(cfg) + f" {med:.4f} | {worst:.4f} |")
    print()


def main():
    exe = build()
    table(exe, "Table 1: 800 iterations, A = 80", "| a | c | median error | worst error |", [(a, c, 800, 80) for a in (0.1, 0.3, 1.0) for c in (0.2, 0.05, 0.01)], lambda t: f"| {t[0]} | {t[1]} |")
    table(exe, "Table 1b: the same with A = 0 (a = 1)", "| a | c | A | median error | worst error |", [(1.0, c, 800, 0) for c in (0.2, 0.05, 0.01)], lambda t: f"| {t[0]} | {t[1]} | {t[3]} |")
    table(exe, "Table 2: c = 0.05", "| a | iterations | A | median error | worst error |", [(a, 0.05, it, A) for a in (0.3, 1.0, 3.0, 10.0) for it in (200, 800, 3000) for A in (0, 80)], lambda t: f"| {t[0]} | {t[2]} | {t[3]} |")
    main_sampled(exe)


def main_sampled(exe):
    tools = (exe, build("vqe-sampled", "examples/vqe/sampled.cho"), build("vqe", "examples/vqe/vqe.cho"))
    cfgs = [(p, it, shots) for p in ((0.3, 0.2), (0.6, 0.3), (1.0, 0.3)) for it in (200, 800) for shots in (100, 1000, 4096)]
    print("Table 3: with shots, A = iterations / 10")
    print("| a | c | iterations | shots per basis | median true error | worst true error |")
    print("|---|---|---|---|---|---|")
    with ThreadPoolExecutor(4) as pool:
        for cfg, (med, worst) in zip(cfgs, pool.map(cell_sampled, [(tools, c) for c in cfgs])):
            print(f"| {cfg[0][0]} | {cfg[0][1]} | {cfg[1]} | {cfg[2]} | {med:.4f} | {worst:.4f} |")
    print()


main()
