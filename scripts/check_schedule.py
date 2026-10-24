#!/usr/bin/env python3
"""Check `sched`: a qubit that waits for others decays, against Qiskit's own scheduler.

    CANCHO=path/to/cancho python3 scripts/check_schedule.py [--exe qsim]

Under `sched`, `qsim` starts every gate as soon as its qubits are free and lets the qubit that
is free earlier idle (and relax) until the other one is. Here the start times come from
Qiskit's `ASAPScheduleAnalysis`, a different implementation of the same rule, and the
decay is Qiskit Aer's thermal-relaxation channel applied to Qiskit's DensityMatrix: for each
gate, the idle gap before it on each of its qubits, the gate, the decay during the gate, and
at the end the gap to the end of the circuit. The result is compared with `qsim`'s density
matrix. The same circuits without `sched` must differ, or the check would prove nothing.

It also writes docs/data/schedule_curve.json: qubit 0 starts as |1> and idles while a chain of
`cx` gates runs on qubits 1 and 2; its chance of still being |1> falls as exp(-t/T1) under
`sched` and stays at 1 without it.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build  # noqa: E402

from qiskit import QuantumCircuit  # noqa: E402
from qiskit.circuit.library import CXGate, HGate, RYGate  # noqa: E402
from qiskit.converters import circuit_to_dag  # noqa: E402
from qiskit.passmanager import PropertySet  # noqa: E402
from qiskit.quantum_info import DensityMatrix, Kraus, Operator  # noqa: E402
from qiskit.transpiler import InstructionDurations  # noqa: E402
from qiskit.transpiler.passes import ASAPScheduleAnalysis, TimeUnitConversion  # noqa: E402
from qiskit_aer.noise import thermal_relaxation_error  # noqa: E402

N = 4
COH = {0: (50000, 70000), 1: (30000, 20000), 2: (40000, 80000), 3: (90000, 100000)}
T1Q, T2Q = 35, 300
DUR1 = {2: 60}
DUR2 = {frozenset((0, 1)): 450}


def d1(q):
    return DUR1.get(q, T1Q)


def d2(a, b):
    return DUR2.get(frozenset((a, b)), T2Q)


def header(sched):
    out = [f"dm {N}"] + [f"coher {q} {a} {b}" for q, (a, b) in COH.items()] + [f"time1 {T1Q}", f"time2 {T2Q}", "dur1 2 60", "dur2 0 1 450"]
    return out + (["sched"] if sched else [])


def qsim_rho(exe, ops, sched):
    text = "\n".join(header(sched) + [" ".join(map(str, o)) for o in ops]) + "\n"
    out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout
    rho = np.zeros((2 ** N, 2 ** N), dtype=complex)
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "rho":
            rho[int(f[1]), int(f[2])] = complex(float(f[3]), float(f[4]))
    return rho


def qiskit_rho(ops):
    qc = QuantumCircuit(N)
    for o in ops:
        if o[0] == "h":
            qc.h(o[1])
        elif o[0] == "ry":
            qc.ry(math.pi * o[2] / o[3], o[1])
        elif o[0] == "x":
            qc.x(o[1])
        else:
            qc.cx(o[1], o[2])
    entries = [(g, q, d1(q)) for g in ("h", "ry", "x") for q in range(N)]
    entries += [("cx", (a, b), d2(a, b)) for a in range(N) for b in range(N) if a != b]
    dur = InstructionDurations(entries, dt=1e-9)
    dag, ps = circuit_to_dag(qc), PropertySet()
    for p in (TimeUnitConversion(dur), ASAPScheduleAnalysis(dur)):
        p.property_set = ps
        r = p.run(dag)
        dag = r if r is not None else dag
    start = ps["node_start_time"]
    rho = DensityMatrix.from_int(0, 2 ** N)
    free = {q: 0 for q in range(N)}

    def relax(rho, q, t):
        return rho.evolve(Kraus(thermal_relaxation_error(*COH[q], t)), qargs=[q]) if t > 0 else rho

    gates = {"h": HGate(), "x": None, "cx": CXGate()}
    for node in dag.topological_op_nodes():
        qs = [dag.find_bit(q).index for q in node.qargs]
        for q in qs:
            rho = relax(rho, q, start[node] - free[q])
        if node.name == "ry":
            rho = rho.evolve(Operator(RYGate(node.op.params[0])), qargs=qs)
        elif node.name == "x":
            rho = rho.evolve(Operator(np.array([[0, 1], [1, 0]])), qargs=qs)
        else:
            rho = rho.evolve(Operator(gates[node.name]), qargs=qs)
        dur_g = d1(qs[0]) if len(qs) == 1 else d2(*qs)
        for q in qs:
            rho = relax(rho, q, dur_g)
            free[q] = start[node] + dur_g
    end = max(free.values())
    for q in range(N):
        rho = relax(rho, q, end - free[q])
    return rho.data


def random_ops(seed, length=14):
    rnd = random.Random(seed)
    ops = []
    for _ in range(length):
        k = rnd.random()
        if k < 0.3:
            ops.append(("h", rnd.randrange(N)))
        elif k < 0.5:
            ops.append(("ry", rnd.randrange(N), rnd.randint(1, 5), rnd.randint(2, 6)))
        else:
            a, b = rnd.sample(range(N), 2)
            ops.append(("cx", a, b))
    return ops


def trace_distance(a, b):
    return 0.5 * float(np.sum(np.abs(np.linalg.eigvalsh(a - b))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    exe = args.exe or os.path.join(tempfile.mkdtemp(prefix="sched-"), "qsim")
    if not args.exe:
        build(args.compiler, "cranelift", exe)
    failed, worst, smallest_gap = False, 0.0, 1.0
    for seed in range(1, 7):
        ops = random_ops(seed)
        want = qiskit_rho(ops)
        got = qsim_rho(exe, ops, True)
        off = qsim_rho(exe, ops, False)
        d, gap = trace_distance(got, want), trace_distance(off, want)
        worst, smallest_gap = max(worst, d), min(smallest_gap, gap)
        ok = d < 1e-9 and gap > 1e-4
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} circuit {seed} ({len(ops)} gates): sched vs Qiskit's ASAP + Aer {d:.1e}; without sched {gap:.1e} away")
    # The decay of a waiting qubit.
    t1, t2 = 50000, 70000
    rows = []
    for k in range(0, 26):
        lines = [f"dm 3", f"coher 0 {t1} {t2}", "time2 2000", "x 0"] + ["cx 1 2"] * k
        res = {}
        for sched in (True, False):
            text = "\n".join(lines[:4] + (["sched"] if sched else []) + lines[4:] + ["probs", "quiet"]) + "\n"
            out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout.splitlines()
            res[sched] = sum(float(l.split()[2]) for l in out if l.startswith("prob ") and l.split()[1][-1] == "1")
        us = 2.0 * k
        rows.append({"p": us, "exact": math.exp(-us * 1000 / t1), "estimate": res[True], "stderr": 0.0, "unscheduled": res[False]})
        if abs(res[True] - rows[-1]["exact"]) > 1e-12 or abs(res[False] - 1.0) > 1e-12:
            print("FAIL decay of a waiting qubit at", us, res)
            failed = True
    print(f"ok   a waiting qubit: P(1) follows exp(-t/T1) to {max(abs(r['estimate'] - r['exact']) for r in rows):.1e}; without sched it stays {rows[-1]['unscheduled']:.6f}")
    with open(os.path.join(ROOT, "docs", "data", "schedule_curve.json"), "w") as f:
        json.dump({"t1_ns": t1, "worst_vs_qiskit": worst, "smallest_gap_without_sched": smallest_gap, "rows": rows}, f, indent=2)
        f.write("\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
