#!/usr/bin/env python3
"""`examples/vqe` against numpy and scipy.

    CANCHO=path/to/cancho OPT=path/to/opt python3 scripts/check_vqe.py [--long]

  1. `vqe-energy` at 300 random angle vectors (1 to 4 layers) equals an independent numpy implementation of the same ansatz and Hamiltonian to 1e-12, and is never below the exact ground
     state energy (the variational principle: a state's energy cannot be lower than the lowest eigenvalue, so a value below it is a bug in the simulator or the Hamiltonian).
  2. The exact ground state energy `vqe` prints (its own Jacobi eigenvalue code) equals numpy's `eigvalsh` to 1e-12.
  3. `vqe-energy` refuses what it should.
  4. `vqe-gradient` (the parameter-shift rule) equals numpy's own parameter-shift gradient to 1e-12 and central finite differences of the energy to 1e-7, and refuses what `vqe-energy` does.
  5. `vqe-sampled` (examples/vqe/README.md, "Sampling"): over many seeds the sampled energy is unbiased and its spread is the predicted `sqrt((Var_Z + h^2 Var_X) / S)`; the read-out bias is the predicted one and
     `--mitigate` removes it; the sampled parameter-shift gradient is unbiased; the same angles and seed give the same output; it refuses bad arguments.
  6. `vqe --method nelder-mead` for 1 and 2 layers (3 with `--long`, about two minutes) and `vqe` (BFGS) for 1 to 4 layers reach the lowest energy that ansatz can reach, which numpy/scipy find independently as the
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
    files = [os.path.join(ROOT, f) for f in ("src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho", "examples/vqe/model.cho", main)]
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


def state_np(theta, layers):
    st = np.zeros(2 ** N)
    st[0] = 1.0
    for l in range(layers + 1):
        u = np.eye(1)
        for q in reversed(range(N)):
            u = np.kron(u, ry(theta[l * N + q]))
        st = u @ st
        if l < layers:
            for m in CX:
                st = m @ st
    return st


def moments(theta, layers):
    """Exact (E_ZZ, E_X, Var_Z, Var_X): the expectations of sum Z Z and sum X and the variances of those observables in the state."""
    st = state_np(theta, layers)
    p = st * st
    f = np.array([sum((1 if (b >> q & 1) == 0 else -1) * (1 if (b >> (q + 1) & 1) == 0 else -1) for q in range(N - 1)) for b in range(2 ** N)], dtype=float)
    ez, vz = float(p @ f), float(p @ (f * f) - (p @ f) ** 2)
    had = np.array([[1.0]])
    for _ in range(N):
        had = np.kron(had, np.array([[1.0, 1.0], [1.0, -1.0]]) / np.sqrt(2.0))
    px = (had @ st) ** 2
    g = np.array([sum(1 if (b >> q & 1) == 0 else -1 for q in range(N)) for b in range(2 ** N)], dtype=float)
    ex, vx = float(px @ g), float(px @ (g * g) - (px @ g) ** 2)
    return ez, ex, vz, vx


def run_sampled(sampled, theta, *flags):
    r = subprocess.run([sampled, *flags], input=" ".join(repr(float(v)) for v in theta), capture_output=True, text=True)
    return r


def check_sampled(sampled, gradient, rng):
    global bad
    layers, S, runs = 1, 256, 400
    theta = rng.uniform(-np.pi, np.pi, N * (layers + 1))
    ez, ex, vz, vx = moments(theta, layers)
    exact = -ez - ex
    vals = np.array([float(run_sampled(sampled, theta, "--shots", str(S), "--seed", str(k)).stdout) for k in range(runs)])
    se = np.sqrt((vz + vx) / S)
    z = abs(vals.mean() - exact) / (se / np.sqrt(runs))
    ratio = float(vals.std(ddof=1) / se)
    good = z < 4.0 and 0.88 < ratio < 1.12
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} vqe-sampled, {runs} seeds, {S} shots per basis: the mean is {vals.mean():+.4f} against the exact {exact:+.4f} ({z:.1f} standard errors of the mean), the spread is {ratio:.3f} of the predicted sqrt((Var_Z + Var_X) / S) = {se:.4f}")
    # read-out error: the predicted bias, and its removal
    P, S2, runs2 = 0.05, 1024, 300
    keep = 1 - 2 * P
    predicted = -ez * keep ** 2 - ex * keep
    raw = np.array([float(run_sampled(sampled, theta, "--shots", str(S2), "--seed", str(k), "--readout", str(P)).stdout) for k in range(runs2)])
    fixed = np.array([float(run_sampled(sampled, theta, "--shots", str(S2), "--seed", str(k), "--readout", str(P), "--mitigate").stdout) for k in range(runs2)])
    zr = abs(raw.mean() - predicted) / (raw.std(ddof=1) / np.sqrt(runs2))
    zf = abs(fixed.mean() - exact) / (fixed.std(ddof=1) / np.sqrt(runs2))
    good = zr < 4.0 and zf < 4.0 and abs(predicted - exact) > 0.1
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} read-out error {P}: the unmitigated mean {raw.mean():+.4f} is the predicted {predicted:+.4f} ({zr:.1f} se; the exact energy is {exact:+.4f}, so the bias is {predicted - exact:+.3f}); mitigated {fixed.mean():+.4f} is the exact energy ({zf:.1f} se)")
    # the sampled gradient is unbiased
    g0 = np.array([float(v) for v in subprocess.run([gradient], input=" ".join(repr(float(v)) for v in theta), capture_output=True, text=True).stdout.split()[1:]])
    runs3 = 200
    gs = np.array([[float(v) for v in run_sampled(sampled, theta, "--shots", "512", "--seed", str(k), "--gradient").stdout.split()[1:]] for k in range(runs3)])
    zg = float(np.max(np.abs(gs.mean(axis=0) - g0) / (gs.std(axis=0, ddof=1) / np.sqrt(runs3))))
    good = zg < 4.5
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} the sampled parameter-shift gradient, {runs3} seeds: every component's mean is the exact gradient's within {zg:.1f} standard errors")
    # no input reaches a trap: the seed mixing once overflowed (a checked `+`) for about 8 percent of angle vectors
    traps = 0
    for t in range(600):
        th = rng.uniform(-np.pi, np.pi, N * int(rng.integers(2, 6)))
        r = run_sampled(sampled, th, "--shots", str(int(rng.integers(1, 200))), "--seed", str(int(rng.integers(0, 10 ** 9))))
        traps += r.returncode != 0 or r.stdout.strip() == ""
    good = traps == 0
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} vqe-sampled on 600 random angle vectors, shot counts and seeds: {traps} failed or trapped")
    a = run_sampled(sampled, theta, "--shots", "64", "--seed", "3")
    b = run_sampled(sampled, theta, "--shots", "64", "--seed", "3")
    c = run_sampled(sampled, theta, "--shots", "64", "--seed", "4")
    th2 = theta.copy()
    th2[-1] += 1e-12
    d = run_sampled(sampled, th2, "--shots", "64", "--seed", "3")
    good = a.stdout == b.stdout and a.stdout != c.stdout and a.stdout != d.stdout and a.stdout.strip() != ""
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} the same angles and seed give the same output, another seed (or angles that differ in the last bit) another one")
    for flags, what in ((("--shots", "0"), "--shots 0"), (("--shots", "5000"), "--shots 5000"), (("--shots", "x"), "--shots x"), ((), "no --shots"),
                        (("--shots", "10", "--readout", "0.6"), "--readout 0.6"), (("--shots", "10", "--readout", "nan"), "--readout nan"), (("--shots", "10", "--seed", "-1"), "--seed -1")):
        r = run_sampled(sampled, theta, *flags)
        good = r.returncode == 2 and r.stdout == ""
        bad += not good
        print(f"{'ok  ' if good else 'FAIL'} vqe-sampled refuses {what} (status 2, nothing on stdout)")
    r = run_sampled(sampled, [1, 2, 3], "--shots", "10")
    good = r.returncode == 2 and r.stdout == ""
    bad += not good
    print(f"{'ok  ' if good else 'FAIL'} vqe-sampled refuses 3 angles")


def main():
    global bad
    long = "--long" in sys.argv
    energy = build("vqe-energy", "examples/vqe/energy.cho")
    gradient = build("vqe-gradient", "examples/vqe/gradient.cho")
    sampled = build("vqe-sampled", "examples/vqe/sampled.cho")
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

    check_sampled(sampled, gradient, rng)

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
