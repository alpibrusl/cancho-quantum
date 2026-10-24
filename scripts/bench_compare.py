#!/usr/bin/env python3
"""Where `qsim` stands: timings and memory against Qiskit's own simulators, on the same circuits.

    CANCHO=path/to/cancho python3 scripts/bench_compare.py [--quick]

Workloads (each built once as a list of operations, then rendered for every simulator):
  h_layer      H on every qubit            memory-bound: each gate streams the whole state
  cx_chain     H, then CX down the chain
  rz_layer     H, then Rz on every qubit   a diagonal gate
  random       depth 20 of random H/T/Ry/CX, seeded
  qft          the quantum Fourier transform, built from H and controlled phases
for n = 10, 14, 18 and 20 qubits (--quick: 10 and 14).

Simulators:
  qsim (cranelift), qsim (llvm)   this project, the whole process: start, parse, run, with `quiet`
  Aer, 1 thread / 4 threads       qiskit-aer's statevector method, C++, `run` only (the circuit ends in `measure_all` with one shot, so the whole state
                                  is simulated and little is copied out; it is built and transpiled to its basis first;
                                  import and transpile are not timed)
  Qiskit Statevector              the pure Python/NumPy reference

Each time is the minimum of 5 runs (3 above 18 qubits). `qsim`'s start-up (a 1-qubit circuit) is measured
and reported, not subtracted. Peak memory of a 20-qubit `h_layer` is read from the child's `ru_maxrss`.
Noisy runs are timed separately: one trajectory of the 10-qubit random circuit with a gate-noise model, 1000 samples,
and the exact density matrix (`dm`) against Aer's density-matrix method and Qiskit's DensityMatrix for 4 to 8 qubits.

Writes docs/data/benchmark.json. Timings depend on the machine; it is recorded, and nothing here is a gate.
"""
import argparse
import json
import math
import os
import platform
import random
import resource
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def workload(name, n, seed=1):
    ops = []
    if name == "h_layer":
        ops = [("h", q) for q in range(n)]
    elif name == "cx_chain":
        ops = [("h", 0)] + [("cx", q, q + 1) for q in range(n - 1)]
    elif name == "rz_layer":
        ops = [("h", q) for q in range(n)] + [("rz", q, 1, q + 3) for q in range(n)]
    elif name == "random":
        rnd = random.Random(seed)
        for _ in range(20):
            for q in range(n):
                g = rnd.choice(["h", "t", "ry"])
                ops.append((g, q) if g != "ry" else ("ry", q, rnd.randint(1, 7), rnd.randint(2, 9)))
            order = list(range(n))
            rnd.shuffle(order)
            for k in range(0, n - 1, 2):
                ops.append(("cx", order[k], order[k + 1]))
    elif name == "qft":
        for q in reversed(range(n)):
            ops.append(("h", q))
            for c in reversed(range(q)):
                ops.append(("cp", c, q, 1, 2 ** (q - c)))
        for q in range(n // 2):
            ops.append(("swap", q, n - 1 - q))
    return ops


def qc_text(n, ops, header="n"):
    return f"{header} {n}\n" + "".join(" ".join(str(x) for x in op) + "\n" for op in ops) + "quiet\n"


def qiskit_circuit(n, ops):
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(n)
    for op in ops:
        g, a = op[0], op[1:]
        if g == "h":
            qc.h(a[0])
        elif g == "t":
            qc.t(a[0])
        elif g == "ry":
            qc.ry(math.pi * a[1] / a[2], a[0])
        elif g == "rz":
            qc.rz(math.pi * a[1] / a[2], a[0])
        elif g == "cx":
            qc.cx(a[0], a[1])
        elif g == "cp":
            qc.cp(math.pi * a[2] / a[3], a[0], a[1])
        elif g == "swap":
            qc.swap(a[0], a[1])
    return qc


def best(fn, runs):
    ts = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return min(ts)


def run_qsim(exe, text):
    subprocess.run([exe], input=text, capture_output=True, text=True, check=True)


def peak_rss_mb(exe, text):
    """Peak resident memory of one run of `exe`, in MiB, from the child's rusage (a fresh process each time)."""
    r = subprocess.run([sys.executable, "-c",
                        "import resource,subprocess,sys;subprocess.run([sys.argv[1]],input=sys.argv[2],capture_output=True,text=True,check=True);"
                        "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)", exe, text], capture_output=True, text=True, check=True)
    return int(r.stdout) / 1024.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    cancho = os.environ.get("CANCHO", "cancho")
    srcs = sorted(os.path.join(ROOT, "src", f) for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
    tmp = tempfile.mkdtemp(prefix="bench-")
    exes = {}
    for backend in ("cranelift", "llvm"):
        exes[backend] = os.path.join(tmp, backend)
        subprocess.run([cancho, "build", *srcs, "--std", "--backend", backend, "-o", exes[backend]], check=True, capture_output=True)
    from qiskit import transpile
    from qiskit.quantum_info import DensityMatrix, Statevector
    from qiskit_aer import AerSimulator
    aer1 = AerSimulator(method="statevector", max_parallel_threads=1, enable_truncation=False)
    aer4 = AerSimulator(method="statevector", max_parallel_threads=4, enable_truncation=False)

    sizes = [10, 14] if args.quick else [10, 14, 18, 20]
    out = {"sizes": sizes, "workloads": {}, "startup_ms": {}, "memory_mib": {}, "noisy": {}}
    for b, exe in exes.items():
        out["startup_ms"][b] = round(1000 * best(lambda: run_qsim(exe, "n 1\nh 0\nquiet\n"), 5), 1)
    for name in ("h_layer", "cx_chain", "rz_layer", "random", "qft"):
        out["workloads"][name] = {}
        for n in sizes:
            ops = workload(name, n)
            runs = 5 if n <= 18 else 3
            row = {"gates": len(ops)}
            text = qc_text(n, ops)
            for b, exe in exes.items():
                row[f"qsim_{b}"] = best(lambda: run_qsim(exe, text), runs)
            qc = qiskit_circuit(n, ops)
            for label, sim in (("aer_1thread", aer1), ("aer_4threads", aer4)):
                circ = qc.copy()
                circ.measure_all()   # one shot sampled from the final state: a cheap result (copying a 16 MiB statevector out to Python is not the simulation)
                t = transpile(circ, sim, optimization_level=0)
                row[label] = best(lambda: sim.run(t, shots=1).result(), runs)
            if n <= 18:
                row["qiskit_statevector"] = best(lambda: Statevector(qc), 3 if n <= 14 else 1)
            out["workloads"][name][str(n)] = row
            print(f"{name:9s} n={n:2d} {len(ops):4d} gates  qsim {row['qsim_cranelift']:.3f}s/{row['qsim_llvm']:.3f}s  aer1 {row['aer_1thread']:.3f}s  aer4 {row['aer_4threads']:.3f}s"
                  + (f"  qiskit {row['qiskit_statevector']:.3f}s" if "qiskit_statevector" in row else ""), flush=True)
    # memory at the largest size
    n = sizes[-1]
    text = qc_text(n, workload("h_layer", n))
    out["memory_mib"]["n"] = n
    out["memory_mib"]["qsim"] = round(peak_rss_mb(exes["llvm"], text), 1)
    out["memory_mib"]["state_vector_mib"] = 16 * 2 ** n / 2 ** 20
    r = subprocess.run([sys.executable, "-c",
                        "import resource;from qiskit_aer import AerSimulator;from qiskit import QuantumCircuit,transpile;"
                        f"n={n};qc=QuantumCircuit(n);[qc.h(q) for q in range(n)];qc.measure_all();s=AerSimulator(method='statevector',max_parallel_threads=1,enable_truncation=False);"
                        "s.run(transpile(qc,s),shots=1).result();print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)"], capture_output=True, text=True, check=True)
    out["memory_mib"]["aer_incl_python"] = round(int(r.stdout) / 1024.0, 1)
    # noisy
    rnd_ops = workload("random", 10)
    noise = "model1 1 1000\nmodel2 1 100\n"
    text = f"n 10\n{noise}" + "".join(" ".join(str(x) for x in op) + "\n" for op in rnd_ops) + "sample 1000\n"
    out["noisy"]["trajectory_10q_random_with_1000_samples"] = {b: best(lambda: run_qsim(exe, text), 5) for b, exe in exes.items()}
    out["noisy"]["density_matrix"] = {}
    from qiskit.quantum_info import Kraus, Operator
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from noise_lib import depol2_kraus, kraus
    for n in (4, 6, 8):
        ops = workload("random", n)
        dmtext = f"dm {n}\nmodel1 1 1000\nmodel2 1 100\n" + "".join(" ".join(str(x) for x in op) + "\n" for op in ops) + "quiet\n"
        row = {"qsim_" + b: best(lambda: run_qsim(exe, dmtext), 3) for b, exe in exes.items()}
        from qiskit_aer.noise import NoiseModel, depolarizing_error
        nm = NoiseModel()
        nm.add_all_qubit_quantum_error(depolarizing_error(4 / 3 * 1 / 1000, 1), ["h", "t", "ry"])
        nm.add_all_qubit_quantum_error(depolarizing_error(16 / 15 * 1 / 100, 2), ["cx"])
        qc = qiskit_circuit(n, ops)
        qc.save_density_matrix()
        sim = AerSimulator(method="density_matrix", noise_model=nm, max_parallel_threads=1)
        t = transpile(qc, sim, optimization_level=0)
        row["aer_density_matrix_1thread"] = best(lambda: sim.run(t, shots=1).result(), 3)
        out["noisy"]["density_matrix"][str(n)] = row
        print(f"dm n={n}: qsim {row['qsim_cranelift']:.3f}s/{row['qsim_llvm']:.3f}s  aer {row['aer_density_matrix_1thread']:.3f}s", flush=True)
    out["machine"] = f"{platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}"
    out["measured"] = time.strftime("%Y-%m-%d")
    out["versions"] = {"qiskit": __import__("qiskit").__version__, "qiskit_aer": __import__("qiskit_aer").__version__, "numpy": __import__("numpy").__version__}
    with open(os.path.join(ROOT, "docs", "data", "benchmark.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
