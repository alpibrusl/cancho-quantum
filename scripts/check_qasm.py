#!/usr/bin/env python3
"""OpenQASM 2.0 checks: what we write is valid, and what Qiskit writes runs.

    CANCHO=path/to/cancho python3 scripts/check_qasm.py [--exe qsim]

For every circuit in tests/qasm/ (written by tools/qcconv.cho):

  1. Qiskit's own parser accepts the file, and for circuits with no
     measurement its statevector equals the checked-in reference to 1e-12:
     so the files are real OpenQASM, meaning what the .qc meant.
  2. `qsim` reading the file prints the reference amplitudes (1e-12) and the
     same measurement bits.
  3. The other direction: the circuit is rebuilt in Qiskit, written out by
     `qiskit.qasm2.dumps`, and fed to `qsim`. A file Qiskit writes with an
     angle outside the subset (a decimal) is counted, not failed: `qsim`
     refuses it by design and says so.
"""
import argparse
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
from qiskit import QuantumCircuit, qasm2
from qiskit.circuit.library import U2Gate
from qiskit.quantum_info import Statevector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build, parse  # noqa: E402

TOL = 1e-12


def read_qc(name):
    lines = [l.split() for l in open(os.path.join(ROOT, "tests", "diff", name + ".qc")) if l.strip()]
    return int(lines[0][1]), [(l[0], *[int(x) for x in l[1:]]) for l in lines[1:]]


def qiskit_circuit(n, ops):
    qc = QuantumCircuit(n, n)
    for k, *a in ops:
        if k in ("h", "x", "y", "z", "s", "t", "sdg", "tdg"):
            getattr(qc, k)(a[0])
        elif k in ("cx", "cz", "swap"):
            getattr(qc, k)(a[0], a[1])
        elif k == "ccx":
            qc.ccx(*a)
        elif k in ("rx", "ry", "rz", "p"):
            getattr(qc, k)(math.pi * a[1] / a[2], a[0])
        elif k == "cp":
            qc.cp(math.pi * a[2] / a[3], a[0], a[1])
        elif k == "m":
            qc.measure(a[0], a[0])
    return qc


def compare(got, want):
    if got[0] != want[0]:
        return f"measurements {got[0]} != {want[0]}"
    worst = 0.0
    for i in set(got[2]) | set(want[2]):
        g, w = got[2].get(i, (0.0, 0.0)), want[2].get(i, (0.0, 0.0))
        worst = max(worst, abs(g[0] - w[0]), abs(g[1] - w[1]))
    return None if worst <= TOL else f"worst amplitude error {worst:.2e}"


def run(exe, text):
    r = subprocess.run([exe], input=text, capture_output=True, text=True)
    return r.returncode, r.stdout


def check_native(exe):
    """`sx`, `sxdg`, `id`, `u2`, `u3` and `u`, which Qiskit writes for the gates of a device's basis and for a general rotation: random circuits of them (and `cx`) on 1 to 4 qubits,
    angles that are rational multiples of pi, written by Qiskit's own `qasm2.dumps` and read by `qsim`, against Qiskit's statevector to 1e-12. A file whose angle Qiskit prints as a
    decimal is counted, not failed, as in the main check."""
    rng = np.random.default_rng(20261026)
    ok = bad = refused = 0
    for case in range(120):
        n = int(rng.integers(1, 5))
        qc = QuantumCircuit(n)
        for _ in range(int(rng.integers(3, 12))):
            q = int(rng.integers(0, n))
            kind = rng.choice(["sx", "sxdg", "id", "u2", "u3", "u", "cx", "h"])
            ang = lambda: math.pi * int(rng.integers(-8, 9)) / int(rng.choice([1, 2, 3, 4, 8]))
            if kind == "cx":
                if n > 1:
                    t = int(rng.choice([k for k in range(n) if k != q]))
                    qc.cx(q, t)
            elif kind in ("sx", "sxdg", "id", "h"):
                getattr(qc, kind)(q)
            elif kind == "u2":
                qc.append(U2Gate(ang(), ang()), [q])
            else:
                qc.u(ang(), ang(), ang(), q)
        text = qasm2.dumps(qc)
        code, out = run(exe, text)
        if code == 3:
            refused += 1
            continue
        if code != 0:
            bad += 1
            print(f"FAIL native case {case}: qsim exit {code}\n{text}")
            continue
        got = parse(out)[2]
        sv = Statevector(qc).data
        worst = max(abs(complex(*got.get(i, (0.0, 0.0))) - sv[i]) for i in range(len(sv)))
        if worst > TOL:
            bad += 1
            print(f"FAIL native case {case}: worst amplitude error {worst:.2e}\n{text}")
        else:
            ok += 1
    print(f"{'ok  ' if not bad else 'FAIL'} native gates (sx sxdg id u2 u3 u): {ok} random circuits agree with Qiskit to {TOL}; {refused} refused for a decimal angle; {bad} wrong")
    return bad == 0 and ok > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    ap.add_argument("--exe")
    args = ap.parse_args()
    exe = args.exe or os.path.join(tempfile.mkdtemp(prefix="qasm-"), "qsim")
    if not args.exe:
        build(args.compiler, "cranelift", exe)
    qdir = os.path.join(ROOT, "tests", "qasm")
    names = sorted(f[:-5] for f in os.listdir(qdir) if f.endswith(".qasm"))
    failed, refused, accepted = [], 0, 0
    for name in names:
        text = open(os.path.join(qdir, name + ".qasm")).read()
        want = parse(open(os.path.join(ROOT, "tests", "diff", name + ".ref")).read())
        problems = []
        qc = qasm2.loads(text)                                   # 1. Qiskit reads our file
        if not any(i.operation.name == "measure" for i in qc.data):
            sv = Statevector(qc).data
            ref = np.zeros(len(sv), dtype=complex)
            for i, (re, im) in want[2].items():
                ref[i] = complex(re, im)
            if np.max(np.abs(sv - ref)) > TOL:
                problems.append("Qiskit's reading of the QASM differs from the reference")
        code, out = run(exe, text)                               # 2. qsim reads our file
        if code != 0:
            problems.append(f"qsim exit {code}")
        else:
            bad = compare(parse(out), want)
            if bad:
                problems.append("qsim: " + bad)
        n, ops = read_qc(name)                                   # 3. qsim reads Qiskit's file
        theirs = qasm2.dumps(qiskit_circuit(n, ops))
        code, out = run(exe, theirs)
        if code == 3:
            refused += 1
        elif code != 0:
            problems.append(f"qsim exit {code} on Qiskit's own QASM")
        else:
            accepted += 1
            bad = compare(parse(out), want)
            if bad:
                problems.append("qsim on Qiskit's QASM: " + bad)
        print(("FAIL " if problems else "ok   ") + f"{name:20s}" + ("; ".join(problems) if problems else ""))
        if problems:
            failed.append(name)
    import json
    with open(os.path.join(qdir, "results.json"), "w") as f:
        json.dump({"files": len(names), "both_parsers": len(names) - len(failed),
                   "qiskit_written_run": accepted, "qiskit_written_refused_decimal": refused}, f, indent=2)
        f.write("\n")
    print(f"\n{len(names) - len(failed)} of {len(names)} files read by both parsers; "
          f"Qiskit-written QASM: {accepted} run, {refused} refused for a decimal angle")
    native = check_native(exe)
    sys.exit(1 if failed or not native else 0)


if __name__ == "__main__":
    main()
