#!/usr/bin/env python3
"""The same kernels in C and in cancho: how much of the speed is the language?

    CANCHO=path/to/cancho python3 scripts/bench_kernels.py

`bench/kernels.c` is `src/gates.cho`'s H, CX and diagonal-gate loops written in C, in two forms: `naive`
(the same loop: visit every index, test the bit) and `tuned` (visit only the pairs). They are built with
clang 18 (LLVM, the backend cancho's LLVM option uses) and gcc 13 at -O3, for the baseline x86-64 target
(no -march=native, as cancho builds). First each variant's amplitudes are checked against `qsim`'s at 10
qubits (1e-12); then the whole process is timed at 20 qubits, min of 5, as in bench_compare.py.
Writes docs/data/benchmark_kernels.json.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKLOADS = {"h_layer": lambda n: [("h", q) for q in range(n)],
             "cx_chain": lambda n: [("h", 0)] + [("cx", q, q + 1) for q in range(n - 1)],
             "rz_layer": lambda n: [("h", q) for q in range(n)] + [("rz", q, 1, q + 3) for q in range(n)]}


def best(argv, text=None, runs=5):
    ts = []
    for _ in range(runs):
        t = time.perf_counter()
        subprocess.run(argv, input=text, capture_output=True, text=True, check=True)
        ts.append(time.perf_counter() - t)
    return min(ts)


def amps(text):
    out = {}
    for line in text.splitlines():
        f = line.split()
        if f and f[0] != "amp":
            out[int(f[0])] = (float(f[1]), float(f[2]))
        elif f:
            out[int(f[1])] = (float(f[2]), float(f[3]))
    return out


def main():
    cancho = os.environ.get("CANCHO", "cancho")
    tmp = tempfile.mkdtemp(prefix="kernels-")
    srcs = sorted(os.path.join(ROOT, "src", f) for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
    qsim = os.path.join(tmp, "qsim")
    subprocess.run([cancho, "build", *srcs, "--std", "--backend", "llvm", "-o", qsim], check=True, capture_output=True)
    exes = {}
    for cc in ("clang", "gcc"):
        exes[cc] = os.path.join(tmp, cc)
        subprocess.run([cc, "-O3", "-o", exes[cc], os.path.join(ROOT, "bench", "kernels.c"), "-lm"], check=True)
    worst = 0.0
    for w, ops in WORKLOADS.items():
        text = "n 10\n" + "".join(" ".join(map(str, o)) + "\n" for o in ops(10))
        want = amps(subprocess.run([qsim], input=text, capture_output=True, text=True, check=True).stdout)
        for cc, exe in exes.items():
            for variant in ("naive", "tuned"):
                got = amps(subprocess.run([exe, variant, w, "10", "dump"], capture_output=True, text=True, check=True).stdout)
                err = max(max(abs(got[i][0] - want.get(i, (0, 0))[0]), abs(got[i][1] - want.get(i, (0, 0))[1])) for i in got)
                worst = max(worst, err)
                if err > 1e-12:
                    sys.exit(f"{cc} {variant} {w}: amplitudes differ from qsim by {err:.2e}")
    print(f"ok   the C kernels agree with qsim to {worst:.1e} on every workload")
    n = 20
    out = {"qubits": n, "workloads": {}, "versions": {"clang": subprocess.run(["clang", "--version"], capture_output=True, text=True).stdout.splitlines()[0],
                                                       "gcc": subprocess.run(["gcc", "--version"], capture_output=True, text=True).stdout.splitlines()[0]}}
    for w, ops in WORKLOADS.items():
        text = f"n {n}\n" + "".join(" ".join(map(str, o)) + "\n" for o in ops(n)) + "quiet\n"
        row = {"qsim_llvm": best([qsim], text)}
        for cc, exe in exes.items():
            for variant in ("naive", "tuned"):
                row[f"{cc}_{variant}"] = best([exe, variant, w, str(n)])
        out["workloads"][w] = row
        print(w, {k: round(v, 3) for k, v in row.items()}, flush=True)
    out["machine"] = f"{platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}"
    out["measured"] = time.strftime("%Y-%m-%d")
    out["worst_difference_from_qsim"] = worst
    with open(os.path.join(ROOT, "docs", "data", "benchmark_kernels.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
