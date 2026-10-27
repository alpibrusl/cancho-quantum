#!/usr/bin/env python3
"""`examples/vqe` against numpy and scipy.

    CANCHO=path/to/cancho OPT=path/to/opt python3 scripts/check_vqe.py [--long]

  1. `vqe-energy` at 300 random angle vectors (1 to 4 layers) equals an independent numpy implementation of the same ansatz and Hamiltonian to 1e-12, and is never below the exact ground
     state energy (the variational principle: a state's energy cannot be lower than the lowest eigenvalue, so a value below it is a bug in the simulator or the Hamiltonian).
  2. The exact ground state energy `vqe` prints (its own Jacobi eigenvalue code) equals numpy's `eigvalsh` to 1e-12.
  3. `vqe-energy` refuses what it should.
  4. `vqe-gradient` (the parameter-shift rule) equals numpy's own parameter-shift gradient to 1e-12 and central finite differences of the energy to 1e-7, and refuses what `vqe-energy` does.
  5. `vqe --method nelder-mead` for 1 and 2 layers (3 with `--long`, about two minutes) and `vqe` (BFGS) for 1 to 4 layers reach the lowest energy that ansatz can reach, which numpy/scipy find independently as the
     best of 30 BFGS runs from random starts: they must agree to 1e-6 (the BFGS runs: the 3- and 4-layer ones must reach the exact energy to 1e-9).
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from scipy.optimize import minimize

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CANCHO = os.environ.get("CANCHO", "cancho")
N = 4
bad = 0


def build(name, main):
    exe = os.path.join(tempfile.mkdtemp(prefix="vqe-"), name)
    files = [os.path.join(ROOT, f) for f in ("src/complex.cho", "src/gates.cho", "src/state.cho", "examples/vqe/model.cho", main)]
    r = subprocess.run([CANCHO, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"cannot build {main}:\n{r.stderr[-1000:]}")
    return exe


def ry(t):
    c, s = np.cos(t / 2), np.sin(t / 2)
    return np.array([[c, -s], [s, c]])


def op(m, q):
    mats = [np.eye(2)] * N
    mats[N - 1 - q] = m
    out = mats[0]
    for k in mats[1:]:
        out = np.kron(out, k)
    return out


X, Z = np.array([[0.0, 1.0], [1.0, 0.0]]), np.diag([1.0, -1.0])
H = -sum(op(Z, q) @ op(Z, q + 1) for q in range(N - 1)) - sum(op(X, q) for q in range(N))
EXACT = float(np.linalg.eigvalsh(H)[0])


def cx(c, t):
    m = np.zeros((2 ** N, 2 ** N))
    for i in range(2 ** N):
        m[i ^ (1 << t) if i >> c & 1 else i, i] = 1.0
    return m


CX = [cx(c, c + 1) for c in range(N - 1)]


def cz(a, b):
    return np.diag([-1.0 if (i >> a & 1) and (i >> b & 1) else 1.0 for i in range(2 ** N)])


CZ = [cz(c, c + 1) for c in range(N - 1)]


def energy_np(theta, layers, chain=None):
    chain = CX if chain is None else chain
    st = np.zeros(2 ** N)
    st[0] = 1.0
    for l in range(layers + 1):
        u = np.eye(1)
        for q in reversed(range(N)):   # the highest qubit is the leftmost factor
            u = np.kron(u, ry(theta[l * N + q]))
        st = u @ st
        if l < layers:
            for m in chain:
                st = m @ st
    return float(st @ H @ st)


def main():
    global bad
    long = "--long" in sys.argv
    energy = build("vqe-energy", "examples/vqe/energy.cho")
    gradient = build("vqe-gradient", "examples/vqe/gradient.cho")
    driver = build("vqe", "examples/vqe/vqe.cho")
    opt = os.environ.get("OPT")
    rng = np.random.default_rng(20261026)
    worst, low = 0.0, 0.0
    for _ in range(300):
        layers = int(rng.integers(1, 5))
        theta = rng.uniform(-np.pi, np.pi, N * (layers + 1))
        r = subprocess.run([energy], input=" ".join(repr(float(v)) for v in theta), capture_output=True, text=True)
        got = float(r.stdout)
        worst = max(worst, abs(got - energy_np(theta, layers)))
        low = min(low, got - EXACT) if low else got - EXACT
        if got < EXACT - 1e-12:
            bad += 1
            print("FAIL energy below the ground state:", got, EXACT)
    ok = worst <= 1e-12
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} vqe-energy at 300 random angle vectors agrees with numpy to {worst:.1e}; the smallest margin above the exact ground state energy among them was {low:.3f} (never negative)")

    # the gradient: numpy's parameter shift, and finite differences
    worst_shift = worst_fd = 0.0
    for _ in range(60):
        layers = int(rng.integers(1, 5))
        theta = rng.uniform(-np.pi, np.pi, N * (layers + 1))
        r = subprocess.run([gradient], input=" ".join(repr(float(v)) for v in theta), capture_output=True, text=True)
        out = [float(v) for v in r.stdout.split()]
        e, g = out[0], np.array(out[1:])
        shift = np.zeros(len(theta))
        fd = np.zeros(len(theta))
        for j in range(len(theta)):
            up, dn = theta.copy(), theta.copy()
            up[j] += np.pi / 2
            dn[j] -= np.pi / 2
            shift[j] = (energy_np(up, layers) - energy_np(dn, layers)) / 2
            up, dn = theta.copy(), theta.copy()
            up[j] += 1e-6
            dn[j] -= 1e-6
            fd[j] = (energy_np(up, layers) - energy_np(dn, layers)) / 2e-6
        worst_shift = max(worst_shift, float(np.max(np.abs(g - shift))), abs(e - energy_np(theta, layers)))
        worst_fd = max(worst_fd, float(np.max(np.abs(g - fd))))
    good = worst_shift <= 1e-12 and worst_fd <= 1e-7
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} vqe-gradient at 60 random angle vectors: equals numpy's parameter-shift gradient to {worst_shift:.1e} and central finite differences to {worst_fd:.1e}")

    for text, what in (("1 2 3", "3 angles"), ("a b c d e f g h", "words"), ("1 2 3 4 5 6 7 nan", "nan"), ("1e999 0 0 0 0 0 0 0", "infinity")):
        for prog, name in ((energy, "vqe-energy"), (gradient, "vqe-gradient")):
            r = subprocess.run([prog], input=text, capture_output=True, text=True)
            good = r.returncode == 2 and r.stdout == ""
            bad += not good
            print(f"{'ok  ' if good else 'FAIL'} {name} refuses {what} (status 2, nothing on stdout)")

    # why the example uses CX and not CZ: with CZ the ansatz stops improving after two layers
    cz_best = {l: min(minimize(energy_np, rng.uniform(-3, 3, N * (l + 1)), args=(l, CZ), method="BFGS").fun for _ in range(30)) for l in (2, 3)}
    cx_best = min(minimize(energy_np, rng.uniform(-3, 3, N * 4), args=(3,), method="BFGS").fun for _ in range(30))
    good = abs(cz_best[2] - cz_best[3]) < 1e-6 and cz_best[3] - EXACT > 0.02 and cx_best - EXACT < 1e-6
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} with CZ entanglers 2 layers reach {cz_best[2]:.8f} and 3 layers {cz_best[3]:.8f} (no better, {cz_best[3] - EXACT:.4f} above the exact energy); with CX, 3 layers reach {cx_best:.8f}")

    if not opt:
        print("skip vqe runs: OPT (a built cancho-opt `opt`) is not set")
    else:
        results = {}
        runs = [("nelder-mead", l) for l in (1, 2) + ((3,) if long else ())] + [("bfgs", l) for l in (1, 2, 3, 4)]
        for method, layers in runs:
            r = subprocess.run([driver, "--method", method, "--layers", str(layers), "--opt", opt, "--energy", energy, "--gradient", gradient, "--maxfev", "30000"], capture_output=True, text=True)
            if r.returncode not in (0, 1):
                bad += 1
                print("FAIL vqe", layers, r.stderr[-300:])
                continue
            got = json.loads(r.stdout)
            results[(method, layers)] = got
            if (method, layers) == ("nelder-mead", 1):
                gap = abs(got["exact"] - EXACT)
                bad += gap > 1e-12
                print(f"{'ok  ' if gap <= 1e-12 else 'FAIL'} the exact ground state energy vqe prints, {got['exact']!r}, equals numpy's to {gap:.1e}")
            best = min(minimize(energy_np, rng.uniform(-3, 3, N * (layers + 1)), args=(layers,), method="BFGS").fun for _ in range(30))
            diff = abs(got["energy"] - best)
            good = diff <= 1e-6
            bad += not good
            extra = ""
            if method == "bfgs" and layers >= 3:
                reach = abs(got["error"]) <= 1e-9
                good = good and reach
                bad += not reach
                extra = " (the exact energy to 1e-9)" if reach else " (NOT the exact energy)"
            print(f"{'ok  ' if good else 'FAIL'} vqe {method} with {layers} layer(s): {got['energy']:.10f} in {got['evaluations']} energy and {got['gradients']} gradient evaluations; the best of 30 scipy BFGS runs finds {best:.10f} (difference {diff:.1e}); error against the exact energy {got['error']:.2e}{extra}")
    print("ok" if not bad else f"FAIL: {bad}")
    sys.exit(1 if bad else 0)


main()
