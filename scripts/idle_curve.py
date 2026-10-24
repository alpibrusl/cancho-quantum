#!/usr/bin/env python3
"""Idle noise against time, exactly: cancho's density matrix, Qiskit Aer's channel, and the formula.

    CANCHO=path/to/cancho python3 scripts/idle_curve.py

Writes docs/data/idle_curve.json for the landing page. A qubit with T1 = 50 us and T2 = 70 us
waits t = 0, 10, ... 100 us (`coher`, `wait`), once from |1> (the chance it is still |1> is
exp(-t/T1)) and once from |+> (the coherence |rho_01| is exp(-t/T2) / 2). `qsim` runs the
density matrix (`dm 1`); Aer's `thermal_relaxation_error` is applied to the same state with
Qiskit's DensityMatrix. The two agree with the formula to rounding.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build  # noqa: E402

import numpy as np  # noqa: E402
from qiskit.circuit.library import HGate, XGate  # noqa: E402
from qiskit.quantum_info import DensityMatrix, Kraus, Operator  # noqa: E402
from qiskit_aer.noise import thermal_relaxation_error  # noqa: E402

T1, T2 = 50000, 70000   # nanoseconds


def run(exe, gate, wait):
    text = f"dm 1\ncoher 0 {T1} {T2}\n{gate} 0\nwait 0 {wait}\n"
    out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout.splitlines()
    rho = {(int(l.split()[1]), int(l.split()[2])): float(l.split()[3]) for l in out if l.startswith("rho ")}
    return rho


def aer(gate, wait):
    rho = DensityMatrix.from_int(0, 2).evolve(Operator({"x": XGate, "h": HGate}[gate]()), qargs=[0])
    if wait:
        rho = rho.evolve(Kraus(thermal_relaxation_error(T1, T2, wait)), qargs=[0])
    return rho.data


def main():
    exe = os.path.join(tempfile.mkdtemp(prefix="idle-"), "qsim")
    build(os.environ.get("CANCHO", "cancho"), "cranelift", exe)
    t1_rows, t2_rows, worst = [], [], 0.0
    for us in range(0, 101, 10):
        ns = us * 1000
        r1, r2 = run(exe, "x", ns), run(exe, "h", ns)
        a1, a2 = aer("x", ns), aer("h", ns)
        pop, coh = r1.get((1, 1), 0.0), abs(r2.get((0, 1), 0.0))
        e1, e2 = math.exp(-ns / T1), math.exp(-ns / T2) / 2
        worst = max(worst, abs(pop - e1), abs(pop - a1[1, 1].real), abs(coh - e2), abs(coh - abs(a2[0, 1])))
        t1_rows.append({"p": us, "exact": e1, "estimate": pop, "stderr": 0.0, "aer": float(a1[1, 1].real)})
        t2_rows.append({"p": us, "exact": e2, "estimate": coh, "stderr": 0.0, "aer": float(abs(a2[0, 1]))})
        print(f"t={us:3d}us  P(1) {pop:.12f} exp {e1:.12f}   |rho01| {coh:.12f} exp {e2:.12f}")
    with open(os.path.join(ROOT, "docs", "data", "idle_curve.json"), "w") as f:
        json.dump({"t1_ns": T1, "t2_ns": T2, "worst_difference": worst, "population": t1_rows, "coherence": t2_rows}, f, indent=2)
        f.write("\n")
    print(f"worst difference between cancho, Aer and the formula: {worst:.2e}")


if __name__ == "__main__":
    main()
