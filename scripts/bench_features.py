#!/usr/bin/env python3
"""Timings of the parts added after docs/benchmark.md's first measurement: the OpenQASM reader (decimal angles, `gate` definitions), and the two variational examples with cancho-opt as the optimiser.

    CANCHO=... OPT=... python3 scripts/bench_features.py [--quick]

Writes docs/data/bench_features.json; `scripts/bench_report.py` puts the tables into docs/benchmark.md. Timings depend on the machine, which is recorded; nothing here is a gate. Every time is the minimum of
5 whole-process runs (3 for the optimiser runs), start-up included, as in the first benchmark. The comparisons are with Qiskit's own reader (`qasm2.loads`) and with scipy's BFGS on a numpy implementation of the same
problem; numpy's costs are first checked against the tools' to 1e-10, so that both do the same work.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CANCHO = os.environ.get("CANCHO", "cancho")
OPT = os.environ.get("OPT")
QUICK = "--quick" in sys.argv
OUT = os.path.join(ROOT, "docs", "data", "bench_features.json")
SRC = ["src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho"]


def build(name, files, backend):
    exe = os.path.join(tempfile.mkdtemp(prefix="bench-"), name)
    r = subprocess.run([CANCHO, "build", *[os.path.join(ROOT, f) for f in files], "--std", "--backend", backend, "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"cannot build {name}:\n{r.stderr[-800:]}")
    return exe


def qsim(backend):
    files = sorted("src/" + f for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
    return build("qsim", files, backend)


def best(fn, runs=5):
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return min(times)


def run_text(exe, text):
    def go():
        r = subprocess.run([exe], input=text, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout[:200] + r.stderr[:200]
    return best(go)


# ---- the OpenQASM reader ------------------------------------------------------------------------------------------------------------------------------------

def program(n, gates, angle, wrap):
    """A seeded circuit of `gates` gates on n qubits: h, t, rz(angle), cx. `wrap`: each gate is a call of a one-gate definition."""
    rng = np.random.default_rng(7)
    head = ["OPENQASM 2.0;", 'include "qelib1.inc";']
    if wrap:
        head += ["gate wh a { h a; }", "gate wt a { t a; }", "gate wrz(x) a { rz(x) a; }", "gate wcx a,b { cx a,b; }"]
    lines = head + [f"qreg q[{n}];"]
    for _ in range(gates):
        q = int(rng.integers(0, n))
        kind = int(rng.integers(0, 4))
        if kind == 0:
            lines.append(f"{'wh' if wrap else 'h'} q[{q}];")
        elif kind == 1:
            lines.append(f"{'wt' if wrap else 't'} q[{q}];")
        elif kind == 2:
            lines.append(f"{'wrz' if wrap else 'rz'}({angle(rng)}) q[{q}];")
        else:
            t = int((q + 1 + rng.integers(0, n - 1)) % n)
            lines.append(f"{'wcx' if wrap else 'cx'} q[{q}],q[{t}];")
    return "\n".join(lines) + "\n"


def qasm_programs(exes):
    pi_angle = lambda rng: f"{int(rng.integers(1, 16))}*pi/{int(rng.choice([2, 3, 4, 8, 16]))}"
    dec_angle = lambda rng: repr(float(rng.uniform(-7, 7)))
    cases = {"multiples of pi": (False, pi_angle), "decimal angles": (False, dec_angle), "every gate a call of a definition": (True, pi_angle)}
    rows = {}
    for n in (4, 20):
        for gates in (300,):
            for label, (wrap, angle) in cases.items():
                text = program(n, gates, angle, wrap)
                row = {"qubits": n, "gates": gates, "bytes": len(text)}
                for backend, exe in exes.items():
                    row[backend] = run_text(exe, text)
                rows[f"{n} qubits, {label}"] = row
    # Qiskit's reader on the same texts, for the parse alone
    from qiskit import qasm2
    for key in rows:
        n = int(key.split()[0])
        label = key.split(", ", 1)[1]
        wrap, angle = cases[label]
        text = program(n, 300, angle, wrap)
        rows[key]["qiskit_loads"] = best(lambda: qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS))
    return rows


def expansion(exes):
    """The cost of one call of a defined gate, isolated from the simulation (4 qubits): N calls of a two-gate definition against the same 2N gates written out."""
    rows = {}
    for calls in ((1000, 10000, 100000) if not QUICK else (1000, 10000)):
        defined = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\ngate g(t) a,b { rz(t*2+0.1) a; cx a,b; }\nqreg q[4];\n" + "".join(f"g({0.001 * (k % 97)}) q[{k % 4}],q[{(k + 1) % 4}];\n" for k in range(calls))
        direct = "OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[4];\n" + "".join(f"rz({0.001 * (k % 97) * 2 + 0.1!r}) q[{k % 4}];\ncx q[{k % 4}],q[{(k + 1) % 4}];\n" for k in range(calls))
        row = {"calls": calls}
        for backend, exe in exes.items():
            d, w = run_text(exe, defined), run_text(exe, direct)
            row[backend] = {"defined": d, "written_out": w, "per_call_us": (d - w) / calls * 1e6}
        rows[str(calls)] = row
    # time to the refusal of the budget: 7 levels of ten calls each, 10^7 calls in all, refused at 200,000
    chain = "OPENQASM 2.0;\nqreg q[2];\ngate g0 a,b { cx a,b; }\n" + "".join(f"gate g{i} a,b {{ " + f"g{i - 1} a,b; " * 10 + "}\n" for i in range(1, 8)) + "g7 q[0],q[1];\n"
    rows["refusal"] = {}
    for backend, exe in exes.items():
        def go():
            r = subprocess.run([exe], input=chain, capture_output=True, text=True)
            assert r.returncode == 3
        rows["refusal"][backend] = best(go, 3)
    return rows


# ---- the variational examples ------------------------------------------------------------------------------------------------------------------------------

N_V = 4


def vqe_np(theta, layers):
    """The ansatz of examples/vqe from matrices (as scripts/check_vqe.py): Ry layers and a CX chain; energy of the transverse-field Ising chain."""
    n = N_V
    psi = np.zeros(1 << n, dtype=complex)
    psi[0] = 1
    for l in range(layers + 1):
        for q in range(n):
            c, s = np.cos(theta[l * n + q] / 2), np.sin(theta[l * n + q] / 2)
            t = psi.reshape([2] * n)
            axis = n - 1 - q
            t = np.moveaxis(np.tensordot(np.array([[c, -s], [s, c]]), t, axes=([1], [axis])), 0, axis)
            psi = t.reshape(-1)
        if l < layers:
            for q in range(n - 1):
                idx = np.arange(1 << n)
                m = ((idx >> q) & 1) == 1
                perm = np.where(m, idx ^ (1 << (q + 1)), idx)
                psi = psi[perm]
    p = np.abs(psi) ** 2
    zz = sum(np.sum(p * (1 - 2 * (((np.arange(1 << n) >> q) & 1) ^ ((np.arange(1 << n) >> (q + 1)) & 1)))) for q in range(n - 1))
    xs = 0.0
    for q in range(n):
        idx = np.arange(1 << n)
        xs += np.real(np.vdot(psi, psi[idx ^ (1 << q)]))
    return float(-zz - xs)


EDGES = [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5), (0, 3), (1, 4), (2, 5)]
CUT = np.array([sum(((b >> a) & 1) != ((b >> c) & 1) for a, c in EDGES) for b in range(64)], dtype=float)


def qaoa_np(theta):
    p = len(theta) // 2
    psi = np.full(64, 1 / 8, dtype=complex)
    bits = np.array([[(b >> q) & 1 for q in range(6)] for b in range(64)])
    z = 1 - 2 * bits
    for l in range(p):
        psi = psi * np.exp(-1j * theta[2 * l] * sum(z[:, a] * z[:, c] for a, c in EDGES) / 2)
        rx = np.array([[np.cos(theta[2 * l + 1]), -1j * np.sin(theta[2 * l + 1])], [-1j * np.sin(theta[2 * l + 1]), np.cos(theta[2 * l + 1])]])
        t = psi.reshape([2] * 6)
        for q in range(6):
            t = np.moveaxis(np.tensordot(rx, t, axes=([1], [5 - q])), 0, 5 - q)
        psi = t.reshape(-1)
    return -float(np.sum(CUT * np.abs(psi) ** 2))


def shift_grad(cost, theta, instances):
    """The parameter-shift gradient by the same rule as the tools: `instances(j)` lists (angle index, multiplier) of the gate instances that angle j drives; each costs two evaluations."""
    g = np.zeros(len(theta))
    for j in range(len(theta)):
        for mult in instances(j):
            e = np.zeros(len(theta))
            e[j] = mult * np.pi / 2
            g[j] += mult * (cost(theta + e) - cost(theta - e)) / 2
    return g


def tool(name, files, backend):
    return build(name, SRC + files, backend)


def variational(backend):
    from scipy.optimize import minimize
    res = {}
    vqe_e = tool("vqe-energy", ["examples/vqe/model.cho", "examples/vqe/energy.cho"], backend)
    vqe_g = tool("vqe-gradient", ["examples/vqe/model.cho", "examples/vqe/gradient.cho"], backend)
    vqe_s = tool("vqe-sampled", ["examples/vqe/model.cho", "examples/vqe/sampled.cho"], backend)
    vqe = tool("vqe", ["examples/vqe/model.cho", "examples/vqe/vqe.cho"], backend)
    q_e = tool("qaoa-energy", ["examples/qaoa/model.cho", "examples/qaoa/energy.cho"], backend)
    q_g = tool("qaoa-gradient", ["examples/qaoa/model.cho", "examples/qaoa/gradient.cho"], backend)
    q_s = tool("qaoa-sampled", ["examples/qaoa/model.cho", "examples/qaoa/sampled.cho"], backend)
    qaoa = tool("qaoa", ["examples/qaoa/model.cho", "examples/qaoa/qaoa.cho"], backend)
    # numpy and the tools do the same work: the same cost at a random point
    rng = np.random.default_rng(3)
    th = rng.uniform(-3, 3, 16)
    got = float(subprocess.run([vqe_e], input=" ".join(map(repr, th)), capture_output=True, text=True).stdout)
    assert abs(got - vqe_np(th, 3)) < 1e-10, (got, vqe_np(th, 3))
    th = rng.uniform(-3, 3, 6)
    got = float(subprocess.run([q_e], input=" ".join(map(repr, th)), capture_output=True, text=True).stdout)
    assert abs(got - qaoa_np(th)) < 1e-10, (got, qaoa_np(th))
    runs = 3
    common = ["--opt", OPT]

    def drive(argv):
        def go():
            r = subprocess.run(argv, capture_output=True, text=True)
            assert r.returncode in (0, 1), r.stderr[-300:]
            go.out = json.loads(r.stdout)
        go.out = None
        t = best(go, runs)
        return t, go.out

    # VQE, 3 layers, 16 angles
    t, out = drive([vqe, "--layers", "3", *common, "--energy", vqe_e, "--gradient", vqe_g])
    # scipy on numpy: BFGS, the same gradient rule, the same start (0.3 everywhere), same tolerance
    x0 = np.full(16, 0.3)
    calls = [0]

    def f(x):
        calls[0] += 1
        return vqe_np(x, 3)
    t_scipy = best(lambda: minimize(f, x0, jac=lambda x: shift_grad(f, x, lambda j: [1]), method="BFGS", options={"gtol": 1e-6, "maxiter": 1000}), runs)
    res["vqe_bfgs"] = {"tool_s": t, "tool_gradients": out["gradients"], "scipy_numpy_s": t_scipy, "error": out["error"]}
    t, out = drive([vqe, "--method", "spsa", "--layers", "3", "--maxiter", "800", *common, "--energy", vqe_e])
    res["vqe_spsa_800_exact"] = {"tool_s": t, "evaluations": out["evaluations"], "true_error": out["true_error"]}
    t, out = drive([vqe, "--method", "spsa", "--layers", "3", "--maxiter", "800", "--shots", "1000", "--seed", "1", *common, "--energy", vqe_e, "--sampled", vqe_s])
    res["vqe_spsa_800_1000_shots"] = {"tool_s": t, "evaluations": out["evaluations"], "shots": out["shots"], "true_error": out["true_error"]}
    # QAOA, 1 to 4 layers, BFGS from the driver's six starts; scipy runs the same six starts
    starts = [(0.4, 0.3), (0.8, 0.2), (1.2, 0.4), (0.2, 0.6), (1.6, 0.1), (0.6, 0.5)]
    for layers in (1, 2, 3, 4):
        t, out = drive([qaoa, "--layers", str(layers), *common, "--energy", q_e, "--gradient", q_g])

        def scipy_run():
            for g0, b0 in starts:
                x = np.array([g0, b0] * layers)
                minimize(qaoa_np, x, jac=lambda y: shift_grad(qaoa_np, y, lambda j: [1] * 9 if j % 2 == 0 else [2] * 6), method="BFGS", options={"gtol": 1e-6, "maxiter": 1000})
        t_scipy = best(scipy_run, runs)
        res[f"qaoa_bfgs_{layers}"] = {"tool_s": t, "tool_gradients": out["gradients"], "scipy_numpy_s": t_scipy, "ratio": out["ratio"]}
    t, out = drive([qaoa, "--method", "spsa", "--layers", "2", "--shots", "1000", "--seed", "1", *common, "--energy", q_e, "--sampled", q_s])
    res["qaoa_spsa_2_1000_shots"] = {"tool_s": t, "evaluations": out["evaluations"], "shots": out["shots"], "ratio": out["ratio"]}
    return res


def main():
    if not OPT:
        sys.exit("OPT (a built cancho-opt `opt`) is required")
    exes = {"llvm": qsim("llvm"), "cranelift": qsim("cranelift")}
    data = {"machine": f"{platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}", "measured": time.strftime("%Y-%m-%d")}
    import qiskit
    data["versions"] = {"qiskit": qiskit.__version__, "numpy": np.__version__}
    import scipy
    data["versions"]["scipy"] = scipy.__version__
    data["qasm"] = qasm_programs(exes)
    data["expansion"] = expansion(exes)
    data["variational"] = variational("llvm")
    json.dump(data, open(OUT, "w"), indent=1)
    print("wrote", OUT)


main()
