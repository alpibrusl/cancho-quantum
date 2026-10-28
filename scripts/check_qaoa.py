#!/usr/bin/env python3
"""`examples/qaoa` against numpy and scipy.

    CANCHO=path/to/cancho OPT=path/to/opt python3 scripts/check_qaoa.py [--mutants]

  1. `qaoa-energy` at 300 random angle vectors (1 to 4 layers) equals an independent numpy implementation of QAOA for MaxCut on the same graph (built from the circuit's matrices, a different code path)
     to 1e-12, and is never below minus the best cut (an expected cut cannot exceed the best one).
  2. `qaoa-gradient` (the parameter-shift rule over every gate instance) equals central finite differences of numpy's cost to 1e-7, and its first number is the cost.
  3. `qaoa-sampled`: over many seeds the sampled cost is unbiased and its spread is the predicted one; with a read-out error P the mean is the predicted `r E + (1 - 2 r) cut` with r = 2 P (1 - P); the same angles and
     seed give the same output; it refuses what it should; 600 random runs never fail or trap.
  4. The refusals of `qaoa-energy` and `qaoa-gradient`.
  5. `qaoa` (BFGS, 6 starts) for 1 to 4 layers reaches the optimum numpy/scipy find independently (best of 40 BFGS runs from random starts) to 1e-6, the best cut it prints is the brute-force one, and the
     ratio rises with the layers; `--method spsa` and `nelder-mead` with shots get within 0.05 of the best cut ratio of their layer count and spend the shots it says.
  `--mutants` builds the tools with one deliberate bug at a time and requires checks 1 and 2 to fail on each.
"""
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from scipy.optimize import minimize

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CANCHO = os.environ.get("CANCHO", "cancho")
N = 6
EDGES = [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (0, 3), (1, 4), (2, 5)]
SRC = ["src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho", "examples/qaoa/model.cho"]
bad = 0

CUT = np.array([sum(((b >> a) & 1) != ((b >> c) & 1) for a, c in EDGES) for b in range(1 << N)], dtype=float)


def build(name, main, root=ROOT, tag="qaoa-"):
    exe = os.path.join(tempfile.mkdtemp(prefix=tag), name)
    files = [os.path.join(root, f) for f in SRC + [main]]
    r = subprocess.run([CANCHO, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"cannot build {main}:\n{r.stderr[-1000:]}")
    return exe


def state_np(theta):
    """QAOA state from matrices: |+>^n, then per layer exp(-i gamma Z_a Z_b / 2) on every edge (a diagonal) and exp(-i beta X) on every qubit."""
    p = len(theta) // 2
    psi = np.full(1 << N, 1 / np.sqrt(1 << N), dtype=complex)
    bits = np.array([[(b >> q) & 1 for q in range(N)] for b in range(1 << N)])
    z = 1 - 2 * bits                                   # eigenvalue of Z_q on basis state b
    for l in range(p):
        gamma, beta = theta[2 * l], theta[2 * l + 1]
        phase = sum(z[:, a] * z[:, c] for a, c in EDGES)
        psi = psi * np.exp(-1j * gamma * phase / 2)
        rx = np.array([[np.cos(beta), -1j * np.sin(beta)], [-1j * np.sin(beta), np.cos(beta)]])
        t = psi.reshape([2] * N)
        for q in range(N):
            axis = N - 1 - q                           # qubit q is bit q of the index
            t = np.moveaxis(np.tensordot(rx, t, axes=([1], [axis])), 0, axis)
        psi = t.reshape(-1)
    return psi


def cost_np(theta):
    psi = state_np(np.asarray(theta, dtype=float))
    return -float(np.sum(CUT * np.abs(psi) ** 2))


def probs_np(theta):
    return np.abs(state_np(np.asarray(theta, dtype=float))) ** 2


def feed(exe, theta, *flags):
    return subprocess.run([exe, *flags], input=" ".join(repr(float(v)) for v in theta), capture_output=True, text=True)


def check_cost_and_gradient(energy, gradient, quiet=False):
    """Checks 1 and 2: True when both pass (a tool that fails to answer, as a mutant that traps does, fails them)."""
    try:
        return cost_and_gradient(energy, gradient, quiet)
    except ValueError:
        if not quiet:
            print("FAIL qaoa-energy or qaoa-gradient gave no answer")
        return False


def cost_and_gradient(energy, gradient, quiet):
    rng = np.random.default_rng(20261101)
    worst_e = worst_g = 0.0
    below = 0
    for _ in range(300):
        p = int(rng.integers(1, 5))
        theta = rng.uniform(-np.pi, np.pi, 2 * p)
        e = float(feed(energy, theta).stdout)
        worst_e = max(worst_e, abs(e - cost_np(theta)))
        below += e < -7.0 - 1e-12
    good_e = worst_e <= 1e-12 and below == 0
    worst_g = worst_c = 0.0
    for _ in range(60):
        p = int(rng.integers(1, 5))
        theta = rng.uniform(-np.pi, np.pi, 2 * p)
        out = [float(v) for v in feed(gradient, theta).stdout.split()]
        h = 1e-6
        fd = np.array([(cost_np(theta + h * np.eye(2 * p)[j]) - cost_np(theta - h * np.eye(2 * p)[j])) / (2 * h) for j in range(2 * p)])
        worst_g = max(worst_g, float(np.max(np.abs(np.array(out[1:]) - fd))))
        worst_c = max(worst_c, abs(out[0] - cost_np(theta)))
    good_g = worst_g <= 1e-7 and worst_c <= 1e-12 and len(out) == 1 + 2 * p
    if not quiet:
        print(f"{'ok  ' if good_e else 'FAIL'} qaoa-energy at 300 random angle vectors equals numpy's QAOA to {worst_e:.1e} (gate 1e-12), and is never below -7, the best cut ({below} below)")
        print(f"{'ok  ' if good_g else 'FAIL'} qaoa-gradient equals central differences of numpy's cost to {worst_g:.1e} (gate 1e-7) at 60 random vectors, and its first number is the cost (to {worst_c:.1e})")
    return good_e and good_g


def check_refusals(energy, gradient, sampled):
    global bad
    for exe, name in ((energy, "qaoa-energy"), (gradient, "qaoa-gradient"), (sampled, "qaoa-sampled")):
        extra = ["--shots", "10"] if name == "qaoa-sampled" else []
        for text, what in (("", "no angles"), ("0.3", "one angle"), ("0.1 0.2 0.3", "three angles"), ("0.1 x", "a word"), ("0.1 nan", "nan"), (" ".join(["0.1"] * 10), "ten angles"), ("0.1 1e999", "an overflow")):
            r = subprocess.run([exe, *extra], input=text, capture_output=True, text=True)
            good = r.returncode == 2 and r.stdout == ""
            bad += not good
            if not good:
                print(f"FAIL {name} should refuse {what}: status {r.returncode}, stdout {r.stdout[:40]!r}")
    print(f"{'ok  ' if not bad else 'FAIL'} the three objectives refuse 0, 1, 3 and 10 angles, a word, nan and an overflow (status 2, nothing on stdout)")


def check_sampled(sampled):
    global bad
    rng = np.random.default_rng(20261102)
    theta = np.array([0.5, 1.1, 0.9, 1.3])
    pr = probs_np(theta)
    exact = float(np.sum(CUT * pr))
    var = float(np.sum(CUT ** 2 * pr) - exact ** 2)
    S, runs = 200, 400
    vals = np.array([float(feed(sampled, theta, "--shots", str(S), "--seed", str(k)).stdout) for k in range(runs)])
    se = np.sqrt(var / S)
    z = abs(-vals.mean() - exact) / (se / np.sqrt(runs))
    ratio = float(vals.std(ddof=1) / se)
    good = z < 4.0 and 0.88 < ratio < 1.12
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} qaoa-sampled, {runs} seeds, {S} shots: the mean cut {-vals.mean():.4f} against the exact {exact:.4f} ({z:.1f} standard errors), the spread is {ratio:.3f} of the predicted sqrt(Var(cut) / S) = {se:.4f}")
    P = 0.08
    r = 2 * P * (1 - P)
    predicted = r * len(EDGES) + (1 - 2 * r) * exact
    raw = np.array([float(feed(sampled, theta, "--shots", "1024", "--seed", str(k), "--readout", str(P)).stdout) for k in range(300)])
    zr = abs(-raw.mean() - predicted) / (raw.std(ddof=1) / np.sqrt(300))
    good = zr < 4.0 and abs(predicted - exact) > 0.3
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} read-out error {P}: the mean cut {-raw.mean():.4f} is the predicted r E + (1 - 2r) cut = {predicted:.4f} ({zr:.1f} se; the exact cut is {exact:.4f})")
    traps = 0
    for _ in range(600):
        th = rng.uniform(-np.pi, np.pi, 2 * int(rng.integers(1, 5)))
        out = feed(sampled, th, "--shots", str(int(rng.integers(1, 200))), "--seed", str(int(rng.integers(0, 10 ** 9))))
        traps += out.returncode != 0 or out.stdout.strip() == ""
    good = traps == 0
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} qaoa-sampled on 600 random angle vectors, shot counts and seeds: {traps} failed or trapped")
    a, b = feed(sampled, theta, "--shots", "64", "--seed", "3"), feed(sampled, theta, "--shots", "64", "--seed", "3")
    c = feed(sampled, theta, "--shots", "64", "--seed", "4")
    good = a.stdout == b.stdout and a.stdout != c.stdout
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} the same angles and seed give the same output, another seed another one")
    for flags, what in ((("--shots", "0"), "--shots 0"), (("--shots", "5000"), "--shots 5000"), ((), "no --shots"), (("--shots", "10", "--readout", "0.6"), "--readout 0.6")):
        r2 = feed(sampled, theta, *flags)
        good = r2.returncode == 2 and r2.stdout == ""
        bad += not good
        print(f"{'ok  ' if good else 'FAIL'} qaoa-sampled refuses {what}")


def check_driver(driver, energy, gradient, sampled, opt):
    global bad
    rng = np.random.default_rng(20261103)
    best_cut = int(CUT.max())
    ratios = []
    for p in (1, 2, 3, 4):
        r = subprocess.run([driver, "--layers", str(p), "--opt", opt, "--energy", energy, "--gradient", gradient], capture_output=True, text=True)
        got = json.loads(r.stdout)
        ref = min(minimize(cost_np, rng.uniform(-np.pi, np.pi, 2 * p), method="BFGS").fun for _ in range(40))
        diff = abs(-got["expected_cut"] - ref)
        good = diff <= 1e-6 and got["best_cut"] == best_cut and abs(cost_np(got["angles"]) + got["expected_cut"]) <= 1e-9
        bad += not good
        ratios.append(got["ratio"])
        print(f"{'ok  ' if good else 'FAIL'} qaoa --layers {p} (BFGS, {got['evaluations']} gradients): expected cut {got['expected_cut']:.9f}, ratio {got['ratio']:.4f}; the best of 40 scipy BFGS runs finds {-ref:.9f} (difference {diff:.1e}); best cut {got['best_cut']} = brute force {best_cut}")
    good = all(a < b for a, b in zip(ratios, ratios[1:])) and ratios[-1] > 0.99
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} the ratio rises with the layers: {', '.join(f'{x:.4f}' for x in ratios)}")
    for method, extra in (("spsa", ["--maxiter", "200"]), ("nelder-mead", ["--maxfev", "2000"])):
        r = subprocess.run([driver, "--method", method, "--layers", "2", "--shots", "200", "--seed", "1", "--starts", "3", "--opt", opt, "--energy", energy, "--sampled", sampled, *extra], capture_output=True, text=True)
        got = json.loads(r.stdout)
        good = got["ratio"] > ratios[1] - 0.05 and got["shots"] == got["evaluations"] * 200
        bad += not good
        print(f"{'ok  ' if good else 'FAIL'} qaoa --method {method} --shots 200, 2 layers: ratio {got['ratio']:.4f} against {ratios[1]:.4f} exact; {got['evaluations']} evaluations, {got['shots']:,} shots")
    for argv, what in ((["--layers", "5"], "--layers 5"), (["--starts", "9"], "--starts 9"), (["--method", "cg"], "--method cg"), (["--shots", "0"], "--shots 0"), (["--shots", "10"], "bfgs with --shots")):
        r = subprocess.run([driver, *argv, "--opt", opt], capture_output=True, text=True)
        good = r.returncode == 2 and r.stdout == ""
        bad += not good
        print(f"{'ok  ' if good else 'FAIL'} qaoa refuses {what} (status 2, nothing on stdout)")


MUTANTS = [
    ("examples/qaoa/model.cho", "gates.rzz(st, n, edge(j) / 8, edge(j) % 8, a);", "gates.rzz(st, n, edge(j) / 8, edge(j) % 8, 0.0 - a);", "the sign of gamma"),
    ("examples/qaoa/model.cho", "var b = 2.0 * theta[2 * l + 1];", "var b = theta[2 * l + 1];", "the factor 2 of the mixer angle"),
    ("examples/qaoa/model.cho", "    } else if k == 4 {\n        return 37;", "    } else if k == 4 {\n        return 36;", "an edge that is a self-loop (4-4)"),
    ("examples/qaoa/model.cho", "    } else if k == 6 {\n        return 3;", "    } else if k == 6 {\n        return 4;", "a wrong end of an edge"),
    ("examples/qaoa/model.cho", "        grad[2 * l + 1] = sum;", "        grad[2 * l + 1] = sum / 2.0;", "the factor 2 of d/d beta"),
    ("examples/qaoa/model.cho", "            sum = sum + (up - down);\n            v = v + 1;", "            sum = sum + (up - down) / 2.0;\n            v = v + 1;", "the shift rule for the mixer"),
    ("examples/qaoa/model.cho", "        grad[2 * l] = sum;", "        grad[2 * l] = sum * 0.5;", "the sum over the edges' RZZs of d/d gamma"),
    ("examples/qaoa/model.cho", "total = total + float_of(cut_of(b)) * (st[2 * b] * st[2 * b] + st[2 * b + 1] * st[2 * b + 1]);", "total = total + float_of(cut_of(b)) * st[2 * b] * st[2 * b];", "the imaginary parts left out of the probabilities"),
    ("examples/qaoa/model.cho", "    var q = 0;\n    while q < n {\n        gates.h(st, n, q);", "    var q = 1;\n    while q < n {\n        gates.h(st, n, q);", "a qubit left out of the first Hadamards"),
]


def mutants():
    ok = True
    for path, a, b, what in MUTANTS:
        d = tempfile.mkdtemp(prefix="qaoa-mut-")
        for f in SRC + ["examples/qaoa/energy.cho", "examples/qaoa/gradient.cho"]:
            os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True)
            text = open(os.path.join(ROOT, f)).read()
            if f == path:
                if text.count(a) != 1:
                    print(f"FAIL mutant '{what}': the text it changes occurs {text.count(a)} times")
                    ok = False
                    break
                text = text.replace(a, b, 1)
            open(os.path.join(d, f), "w").write(text)
        else:
            energy, gradient = build("qaoa-energy", "examples/qaoa/energy.cho", d, "qaoa-mut-"), build("qaoa-gradient", "examples/qaoa/gradient.cho", d, "qaoa-mut-")
            if check_cost_and_gradient(energy, gradient, quiet=True):
                print(f"FAIL mutant '{what}' SURVIVED")
                ok = False
            else:
                print(f"ok   mutant killed: {what}")
        shutil.rmtree(d, ignore_errors=True)
    return ok


def main():
    global bad
    energy = build("qaoa-energy", "examples/qaoa/energy.cho")
    gradient = build("qaoa-gradient", "examples/qaoa/gradient.cho")
    sampled = build("qaoa-sampled", "examples/qaoa/sampled.cho")
    driver = build("qaoa", "examples/qaoa/qaoa.cho")
    bad += not check_cost_and_gradient(energy, gradient)
    check_refusals(energy, gradient, sampled)
    check_sampled(sampled)
    opt = os.environ.get("OPT")
    if not opt:
        print("skip qaoa runs: OPT (a built cancho-opt `opt`, with --method bfgs and spsa) is not set")
    else:
        check_driver(driver, energy, gradient, sampled, opt)
    if "--mutants" in sys.argv:
        bad += not mutants()
    print("ok" if not bad else f"FAIL: {bad}")
    sys.exit(1 if bad else 0)


main()
