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
import re
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


def check_decimal_circuits(exe):
    """Angles written the ways Qiskit and people write them (a decimal, an exponent, a sign, `0.25*pi`, `2*pi/3`, a plain integer), 150 random circuits of rx ry rz u1 cu1 u3 against Qiskit's statevector to 1e-12 (Qiskit
    reads the same text); and the texts that are not angles must be refused with status 3 and not run."""
    rng = np.random.default_rng(20261028)
    forms = [lambda x: repr(x), lambda x: f"{x:.17e}", lambda x: f"{x:.6f}", lambda x: f"{-abs(x)!r}", lambda x: f"{x / math.pi!r}*pi", lambda x: f"{abs(x) * 3:.5f}*pi/3", lambda x: f"{int(x * 100)}", lambda x: f"{x:.3g}"]
    ok = bad = 0
    for case in range(150):
        n = int(rng.integers(1, 4))
        lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];"]
        for _ in range(int(rng.integers(2, 9))):
            q = int(rng.integers(0, n))
            a = lambda: forms[int(rng.integers(0, len(forms)))](float(rng.uniform(-7, 7)))
            kind = rng.choice(["rx", "ry", "rz", "u1", "cp", "u3", "h", "cx"])
            if kind in ("rx", "ry", "rz", "u1"):
                lines.append(f"{kind}({a()}) q[{q}];")
            elif kind == "u3":
                lines.append(f"u3({a()},{a()},{a()}) q[{q}];")
            elif kind == "cp" and n > 1:
                t = int(rng.choice([k for k in range(n) if k != q]))
                lines.append(f"cu1({a()}) q[{q}],q[{t}];")
            elif kind == "cx" and n > 1:
                t = int(rng.choice([k for k in range(n) if k != q]))
                lines.append(f"cx q[{q}],q[{t}];")
            elif kind == "h":
                lines.append(f"h q[{q}];")
        text = "\n".join(lines) + "\n"
        code, out = run(exe, text)
        sv = Statevector(qasm2.loads(text)).data
        got = parse(out)[2] if code == 0 else {}
        worst = max(abs(complex(*got.get(i, (0.0, 0.0))) - sv[i]) for i in range(len(sv))) if code == 0 else 1.0
        if code != 0 or worst > TOL:
            bad += 1
            print(f"FAIL decimal circuit {case}: exit {code}, worst {worst:.2e}\n{text}")
        else:
            ok += 1
    refusals = 0
    for angle in ("1e", "pi*", ".", "abc", "1/0", "1e50", "1..2", "-", "pi/", "2*"):
        code, out = run(exe, f"OPENQASM 2.0;\nqreg q[1];\nrz({angle}) q[0];\n")
        if code == 3 and out.strip() == "error: an angle must be a number or a multiple of pi (0.785, pi, -pi/2, 3*pi/4)" or code == 3 and out.startswith("error:"):
            refusals += 1
        else:
            bad += 1
            print(f"FAIL angle {angle!r} should be refused with status 3: exit {code}, {out[:80]!r}")
    print(f"{'ok  ' if not bad else 'FAIL'} decimal angles: {ok} random circuits agree with Qiskit to {TOL}; {refusals} of 10 malformed angles refused with status 3; {bad} wrong")
    return bad == 0


def check_controlled(exe):
    """`cy`, `ch`, `crz`, `rzz` and `cswap`, which `qelib1.inc` defines and Qiskit writes: 120 random circuits of them with the usual gates around, against Qiskit's statevector to 1e-12 (Qiskit's are the true
    controlled matrices, so a global phase left over by a decomposition would show here)."""
    rng = np.random.default_rng(20261029)
    ok = bad = 0
    for case in range(120):
        n = int(rng.integers(2, 5))
        lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];"]
        for _ in range(int(rng.integers(4, 14))):
            kind = str(rng.choice(["cy", "ch", "crz", "rzz", "cswap", "h", "t", "rx", "cx", "ry"]))
            qs = [int(x) for x in rng.permutation(n)]
            ang = f"{float(rng.uniform(-7, 7))!r}"
            if kind in ("cy", "ch", "cx"):
                lines.append(f"{kind} q[{qs[0]}],q[{qs[1]}];")
            elif kind in ("crz", "rzz"):
                lines.append(f"{kind}({ang}) q[{qs[0]}],q[{qs[1]}];")
            elif kind == "cswap" and n >= 3:
                lines.append(f"cswap q[{qs[0]}],q[{qs[1]}],q[{qs[2]}];")
            elif kind in ("rx", "ry"):
                lines.append(f"{kind}({ang}) q[{qs[0]}];")
            elif kind in ("h", "t"):
                lines.append(f"{kind} q[{qs[0]}];")
        text = "\n".join(lines) + "\n"
        code, out = run(exe, text)
        sv = Statevector(qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)).data
        got = parse(out)[2] if code == 0 else {}
        worst = max(abs(complex(*got.get(i, (0.0, 0.0))) - sv[i]) for i in range(len(sv))) if code == 0 else 1.0
        if code != 0 or worst > TOL:
            bad += 1
            print(f"FAIL controlled case {case}: exit {code}, worst {worst:.2e}\n{text}")
        else:
            ok += 1
    print(f"{'ok  ' if not bad else 'FAIL'} cy ch crz rzz cswap: {ok} random circuits agree with Qiskit to {TOL}; {bad} wrong")
    return bad == 0


def check_classical(exe):
    """`creg`, `measure q[i] -> c[j]` and `if (c==k)`: random programs whose measurements are certain (the gates only move basis states about and change their phase, so every outcome is fixed, and so is every
    condition), the final state against Aer's, which runs the same `if`. Then the texts that are not valid are refused with status 2 and not run."""
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    rng = np.random.default_rng(20261029)
    ok = bad = taken = 0
    for case in range(120):
        n = int(rng.integers(2, 5))
        sizes = [int(rng.integers(1, 4)), int(rng.integers(1, 4))]
        lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];", f"creg a[{sizes[0]}];", f"creg b[{sizes[1]}];"]
        for _ in range(int(rng.integers(5, 16))):
            qs = [int(x) for x in rng.permutation(n)]
            kind = str(rng.choice(["x", "y", "z", "s", "t", "cx", "cy", "cz", "swap", "ccx", "cswap", "rz", "crz", "measure", "measure", "if", "if"]))
            def gate():
                if kind in ("x", "y", "z", "s", "t"):
                    return f"{kind} q[{qs[0]}];"
                if kind == "rz":
                    return f"rz({float(rng.uniform(-7, 7))!r}) q[{qs[0]}];"
                if kind == "crz":
                    return f"crz({float(rng.uniform(-7, 7))!r}) q[{qs[0]}],q[{qs[1]}];"
                if kind in ("cx", "cy", "cz", "swap"):
                    return f"{kind} q[{qs[0]}],q[{qs[1]}];"
                if kind == "ccx" and n >= 3:
                    return f"ccx q[{qs[0]}],q[{qs[1]}],q[{qs[2]}];"
                if kind == "cswap" and n >= 3:
                    return f"cswap q[{qs[0]}],q[{qs[1]}],q[{qs[2]}];"
                return f"x q[{qs[0]}];"
            if kind == "measure":
                reg = int(rng.integers(0, 2))
                lines.append(f"measure q[{qs[0]}] -> {'ab'[reg]}[{int(rng.integers(0, sizes[reg]))}];")
            elif kind == "if":
                reg = int(rng.integers(0, 2))
                kind = str(rng.choice(["x", "z", "cx", "swap", "rz"]))
                lines.append(f"if({'ab'[reg]}=={int(rng.integers(0, 1 << sizes[reg]))}) {gate()}")
            else:
                lines.append(gate())
        text = "\n".join(lines) + "\n"
        code, out = run(exe, text)
        qc = qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
        qc.save_statevector()
        sv = AerSimulator(method="statevector").run(transpile(qc, AerSimulator(), optimization_level=0), shots=1).result().get_statevector().data
        got = parse(out)[2] if code == 0 else {}
        worst = max(abs(complex(*got.get(i, (0.0, 0.0))) - sv[i]) for i in range(len(sv))) if code == 0 else 1.0
        if code != 0 or worst > 1e-9:
            bad += 1
            print(f"FAIL classical case {case}: exit {code}, worst {worst:.2e}\n{text}")
        else:
            ok += 1
    refused = 0
    base = "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\n"
    for body, want in (("measure q[0] -> d[0];", 2), ("measure q[0] -> c[5];", 2), ("if(d==1) x q[0];", 2), ("if(c=1) x q[0];", 2), ("if(c==1 x q[0];", 2),
                       ("creg e[0];", 3), ("creg e[1];creg f[1];creg g[1];creg h[1];", 3)):
        code, out = run(exe, base + body + "\n")
        if code == want:
            refused += 1
        else:
            bad += 1
            print(f"FAIL {body!r} should end with status {want}: exit {code}, {out[:80]!r}")
    print(f"{'ok  ' if not bad else 'FAIL'} creg, measure -> and if: {ok} random programs end in Aer's state to 1e-9; {refused} of 7 invalid ones refused with the right status; {bad} wrong")
    return bad == 0


OLD_REV = "5070a8e"     # the last commit before gate definitions: the reader whose angles must not move


def build_old(compiler):
    """`qsim` built from OLD_REV (None when the revision is not in this clone)."""
    d = tempfile.mkdtemp(prefix="qasm-old-")
    r = subprocess.run(f"git -C {ROOT} archive {OLD_REV} src | tar -x -C {d}", shell=True, capture_output=True)
    if r.returncode:
        return None
    exe = os.path.join(d, "qsim")
    srcs = [os.path.join(d, "src", f) for f in sorted(os.listdir(os.path.join(d, "src"))) if f.endswith(".cho")]
    subprocess.run([compiler, "build", *srcs, "--std", "-o", exe], check=True)
    return exe


def old_angle_texts(rng, count):
    out = []
    for _ in range(count):
        sign = str(rng.choice(["", "-"]))
        N = int(rng.choice([1, 2, 3, 5, 7, 12, 31, 97, 12345, 0, 100000]))
        M = int(rng.choice([1, 2, 3, 4, 8, 97, 1000, 16]))
        D = str(rng.choice(["0.5", "1.5707963267948966", "3.14", "0.25", "2.0", "7.853981633974483", "1e-3", "123.456", "0.1"]))
        forms = ["pi", f"{N}*pi", f"pi/{M}", f"{N}*pi/{M}", "0", D, f"{D}*pi", f"{D}*pi/{M}", f"{N}", f"{N}/{M}", f"{N} * pi / {M}", "2*pi/3.5", f"{D}/{M}", f"{D}*pi/{D}"]
        out.append(sign + str(rng.choice(forms)))
    return out


def check_old_angles(exe, old):
    """Check 1 of docs/qasm-gates.md section 6: the angles of the old grammar did not move. Every text of the old grammar, in rx ry rz p u1 u2 u3 cp, gives the same bytes from the old reader and the new."""
    if old is None:
        print(f"skip old-angle check: revision {OLD_REV} is not in this clone")
        return True
    rng = np.random.default_rng(20261030)
    same = bad = 0
    progs = []
    for a in old_angle_texts(rng, 5000):
        progs.append(f"OPENQASM 2.0;\nqreg q[2];\nh q[0];\n{rng.choice(['rx', 'ry', 'rz', 'p', 'u1'])}({a}) q[0];\ncx q[0],q[1];\n")
    for a, b, c in zip(old_angle_texts(rng, 1500), old_angle_texts(rng, 1500), old_angle_texts(rng, 1500)):
        progs.append(f"OPENQASM 2.0;\nqreg q[2];\nh q[0];\nu3({a},{b},{c}) q[0];\nu2({b},{c}) q[1];\ncp({a}) q[0],q[1];\n")
    for text in progs:
        o = subprocess.run([old], input=text, capture_output=True, text=True)
        n = subprocess.run([exe], input=text, capture_output=True, text=True)
        if o.returncode == 0:
            if (o.returncode, o.stdout) == (n.returncode, n.stdout):
                same += 1
            else:
                bad += 1
                if bad < 5:
                    print(f"FAIL old angle text differs:\n{text}\nold {o.stdout[:100]!r}\nnew {n.returncode} {n.stdout[:100]!r}")
    print(f"{'ok  ' if not bad else 'FAIL'} the old angle grammar did not move: {same} of {len(progs)} programs give the same bytes from the old reader (rev {OLD_REV}) and the new; {bad} differ")
    return bad == 0


def amplitudes_vs_qiskit(exe, text):
    code, out = run(exe, text)
    if code != 0:
        return code, 1.0
    sv = Statevector(qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)).data
    got = parse(out)[2]
    return 0, max(abs(complex(*got.get(i, (0.0, 0.0))) - sv[i]) for i in range(len(sv)))


def check_qiskit_gates(exe):
    """Check 2: circuits with custom gates, nested, with names that share their first seven characters (the old reader would have taken them for one word), written by Qiskit's `qasm2.dumps` together with the
    definitions of the library gates it writes (ryy, iswap, ecr, dcx), against Qiskit's statevector to 1e-12."""
    from qiskit.circuit.library import RYYGate, ECRGate, iSwapGate, DCXGate
    rng = np.random.default_rng(20261030)
    ok = bad = 0
    for case in range(80):
        n = int(rng.integers(3, 13))
        qc = QuantumCircuit(n)
        made = []
        prefix = str(rng.choice(["gate_QFT_", "measured_", "my_long_gate_", "cswapper"]))
        for g in range(int(rng.integers(1, 4))):
            k = int(rng.integers(2, 4))
            sub = QuantumCircuit(k, name=f"{prefix}{g}{int(rng.integers(10**8, 10**9))}")
            for _ in range(int(rng.integers(2, 7))):
                kind = str(rng.choice(["h", "t", "rx", "ry", "rz", "cx", "cz", "swap", "nest"]))
                qs = [int(x) for x in rng.permutation(k)]
                ang = float(rng.uniform(-7, 7))
                if kind in ("h", "t"):
                    getattr(sub, kind)(qs[0])
                elif kind in ("rx", "ry", "rz"):
                    getattr(sub, kind)(ang, qs[0])
                elif kind in ("cx", "cz", "swap"):
                    getattr(sub, kind)(qs[0], qs[1])
                elif made:
                    gate = made[int(rng.integers(0, len(made)))]
                    if gate.num_qubits <= k:
                        sub.append(gate, qs[: gate.num_qubits])
            made.append(sub.to_gate())
        for _ in range(int(rng.integers(3, 9))):
            qs = [int(x) for x in rng.permutation(n)]
            kind = int(rng.integers(0, 4))
            if kind == 0 and made:
                gate = made[int(rng.integers(0, len(made)))]
                qc.append(gate, qs[: gate.num_qubits])
            elif kind == 1:
                qc.append(RYYGate(float(rng.uniform(-3, 3))), qs[:2])
            elif kind == 2:
                qc.append([iSwapGate(), ECRGate(), DCXGate()][int(rng.integers(0, 3))], qs[:2])
            else:
                qc.h(qs[0])
        text = qasm2.dumps(qc)
        code, worst = amplitudes_vs_qiskit(exe, text)
        if code != 0 or worst > TOL:
            bad += 1
            print(f"FAIL qiskit custom gates case {case}: exit {code}, worst {worst:.2e}\n{text[:900]}")
        else:
            ok += 1
    print(f"{'ok  ' if not bad else 'FAIL'} Qiskit's definitions (custom, nested, long names, ryy iswap ecr dcx): {ok} random circuits agree with Qiskit to {TOL}; {bad} wrong")
    return bad == 0


EXPRS = ["a", "-a", "a/2", "a*2+b", "(a+b)/3", "pi/2-a", "2*pi*a", "sin(a)", "cos(a)*b", "sqrt(a*a+1)", "a^2", "exp(-a)", "ln(a+2)", "-(a-b)*1.5", "tan(a/3)", "a-b-1", "2^a", "3*a/4", "pi*a/3", "-pi/2+b"]
ARGS = ["0.7", "pi/4", "1.3", "0.25*pi", "1e-1", "sqrt(2)", "1/3", "0.5"]    # small and positive, so that `ln(a+2)` and `sqrt` stay in their domain whatever the nesting passes on


def check_expressions(exe):
    """Check 3: gate definitions written by hand with the angle names in expressions of the whole grammar (nested calls pass expressions on), 150 random programs against Qiskit's reading of the same text."""
    rng = np.random.default_rng(20261031)
    ok = bad = 0
    for case in range(150):
        n = int(rng.integers(2, 5))
        pick = lambda: str(rng.choice(EXPRS))
        arg = lambda: str(rng.choice(ARGS))
        lines = ["OPENQASM 2.0;", 'include "qelib1.inc";']
        lines.append(f"gate inner(a,b) x,y {{ rx({pick()}) x; cx x,y; rz({pick()}) y; u3({pick()},{pick()},{pick()}) x; }}")
        only_a = lambda: re.sub(r"\bb\b", "a", pick())
        lines.append(f"gate outer(a) p,q,r {{ inner(a*2,{only_a()}) p,q; crz({only_a()}) q,r; inner(-a,pi/3) r,p; }}")
        lines.append(f"qreg q[{n}];")
        for _ in range(int(rng.integers(2, 7))):
            qs = [int(x) for x in rng.permutation(n)]
            kind = str(rng.choice(["inner", "outer", "h", "rx"]))
            if kind == "inner":
                lines.append(f"inner({arg()},{arg()}) q[{qs[0]}],q[{qs[1]}];")
            elif kind == "outer" and n >= 3:
                lines.append(f"outer({arg()}) q[{qs[0]}],q[{qs[1]}],q[{qs[2]}];")
            elif kind == "rx":
                lines.append(f"rx({arg()}) q[{qs[0]}];")
            else:
                lines.append(f"h q[{qs[0]}];")
        text = ("", " ", "\n")[case % 3].join(lines) + "\n"     # a third of them with nothing between statements, so that a call is followed at once by the next one
        code, worst = amplitudes_vs_qiskit(exe, text)
        if code != 0 or worst > TOL:
            bad += 1
            print(f"FAIL expression case {case}: exit {code}, worst {worst:.2e}\n{text}")
        else:
            ok += 1
    for expression in ("2*3", "2*3*pi/12", "(2+1)*pi/6", "-(3*pi)/4", "pi*3/4", "pi/2/2", "pi*2*3/12", "1/2*pi", "2^3*0.1", "2^3^2/100", "-2^2*0.1", "2^-1", "3*2*0.5", "-(-pi)/5", "+pi/7", "(pi)", "((2))*pi/9"):
        text = f"OPENQASM 2.0;\ninclude \"qelib1.inc\";\nqreg q[1];\nh q[0];\nrz({expression}) q[0];\nrx({expression}) q[0];\n"
        code, worst = amplitudes_vs_qiskit(exe, text)
        if code != 0 or worst > TOL:
            bad += 1
            print(f"FAIL angle {expression!r}: exit {code}, worst {worst:.2e}")
        else:
            ok += 1
    print(f"{'ok  ' if not bad else 'FAIL'} angle expressions: {ok} random definitions and fixed expressions agree with Qiskit to {TOL}; {bad} wrong")
    return bad == 0


def gate_refusals():
    """(text, expected status): every row of the limits table of docs/qasm-gates.md section 5."""
    head = "OPENQASM 2.0;\nqreg q[3];\n"
    def chain(top):
        return "gate g0 a,b { cx a,b; }\n" + "".join(f"gate g{i} a,b {{ " + "g%d a,b; " % (i - 1) * 10 + "}\n" for i in range(1, top + 1)) + f"g{top} q[0],q[1];\n"
    return [
        (head + "gate g a { x a; }\ngate g a { z a; }\n", 3),
        (head + "nosuch q[0];\n", 3),
        (head + "opaque op a;\n", 3),
        (head + "gate g a { measure a -> c[0]; }\ncreg c[1];\ng q[0];\n", 3),
        (head + "gate g(t) a { rz(t) a; }\ng q[0];\n", 3),
        (head + "gate g a { x a; }\ng q[0],q[1];\n", 2),
        (head + "gate g a,b { cx a,b; }\ng q[1],q[1];\n", 2),
        (head + "gate g a { g a; }\ng q[0];\n", 3),
        (head + chain(7), 3),    # eight deep, ten calls each: 10^7 calls, over the budget of 200,000
        (head + chain(8), 3),    # nine deep: over the depth
        (head + "creg c[1];\nmeasured q[0] -> c[0];\n", 3),    # not `measure`
        (head + "gate g a { " + "x a; " * 5000 + "}\n", 3),
        (head + "".join(f"gate g{i} a {{ x a; }}\n" for i in range(65)), 3),
        (head + "gate g " + ",".join(f"a{i}" for i in range(25)) + " { x a0; }\n", 3),
        (head + "gate g a { x a;", 2),
        (head + "gate g(t) a { rz(1/0) a; }\ng(1) q[0];\n", 3),
        (head + "gate g a { gate h b { x b; } }\n", 3),
        (head + "gate g a { x a; }\ng q[7];\n", 2),
        (head + "rz(1/0) q[0];\n", 3),
        (head + "rz(sqrt(-1)) q[0];\n", 3),
        (head + "rz(ln(0)) q[0];\n", 3),
        (head + "gate g a { x b; }\ng q[0];\n", 2),
        (head + "x q[0];\n}\n", 2),
    ]


def check_gate_refusals(exe):
    """Check 4: every row of the limits table is refused with its status (nothing on standard output that is not the error, and never a trap), and 1,200 mutated programs (a character deleted, doubled or replaced) end in status 0, 2 or 3."""
    ok = bad = 0
    for text, want in gate_refusals():
        r = subprocess.run([exe], input=text, capture_output=True, text=True, timeout=120)
        if r.returncode == want:
            ok += 1
        else:
            bad += 1
            print(f"FAIL expected status {want}, got {r.returncode}: {text[:160]!r} {r.stdout[:80]!r}")
    rng = np.random.default_rng(20261031)
    seeds = [
        'OPENQASM 2.0;\ninclude "qelib1.inc";\ngate inner(a,b) x,y { rx(a*2+b) x; cx x,y; rz(-a/3+pi) y; }\ngate outer(a) p,q,r { inner(a,0.5) p,q; crz(sin(a)) q,r; }\nqreg q[3];\ncreg c[2];\nouter(0.7) q[0],q[1],q[2];\nmeasure q[0] -> c[0];\nif(c==1) inner(1,2) q[1],q[2];\n',
        'OPENQASM 2.0;\nqreg q[2];\ngate g(t) a,b { rz(t^2) a; cx a,b; ry(-t) b; } // note\ng(1.5) q[0],q[1];\ng(pi/3) q[1],q[0];\n',
    ]
    fuzz = 0
    for _ in range(1200):
        text = seeds[int(rng.integers(0, len(seeds)))]
        for _ in range(int(rng.integers(1, 4))):
            at = int(rng.integers(0, len(text)))
            how = int(rng.integers(0, 3))
            ch = str(rng.choice(list("(){};,/*+-^.0129eqabcgipnt [] \n")))
            if how == 0:
                text = text[:at] + text[at + 1:]
            elif how == 1:
                text = text[:at] + text[at] + text[at:]
            else:
                text = text[:at] + ch + text[at + 1:]
        try:
            r = subprocess.run([exe], input=text, capture_output=True, text=True, timeout=60)
            code = r.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        if code in (0, 2, 3):
            fuzz += 1
        else:
            bad += 1
            if bad < 6:
                print(f"FAIL mutated program ended with {code}:\n{text}")
    print(f"{'ok  ' if not bad else 'FAIL'} gate refusals: {ok} of {len(gate_refusals())} limit rows refused with their status; {fuzz} of 1200 mutated programs ended in 0, 2 or 3 and never a trap; {bad} wrong")
    return bad == 0


def check_gate_defs(exe, old):
    return check_old_angles(exe, old) and check_qiskit_gates(exe) and check_expressions(exe) and check_gate_refusals(exe)


GATE_MUTANTS = [
    ("src/qasm.cho", "b = b * a2;", "b = b + a2;", "a pi multiple divided by an integer"),
    ("src/qasm.cho", "                    a = a * a2;\n                    v = float_of(a);", "                    a = a + a2;\n                    v = float_of(a);", "an integer times an integer"),
    ("src/qasm.cho", "                    k = 1;\n                    a = a * a2;\n                    b = b2;", "                    k = 1;\n                    a = a + a2;\n                    b = b2;", "an integer times a pi multiple"),
    ("src/qasm.cho", "        let (k2, a2, b2, v2) = unary(io, la);\n        if k2 < 0 {\n            return bad_value();\n        }\n        let r = math.pow(v, v2);", "        let (k2, a2, b2, v2) = power(io, la);\n        if k2 < 0 {\n            return bad_value();\n        }\n        let r = math.pow(v, v2);", "^ binds the exponent too tightly"),
    ("src/qasm.cho", "        if k == 1 {\n            return (1, 0 - a, b, 0.0 - v);\n        }", "        if k == 1 {\n            return (1, a, b, 0.0 - v);\n        }", "a lost unary minus on a pi multiple"),
    ("src/qasm.cho", "                if op == '+' {\n                    v = v + v2;", "                if op == '-' {\n                    v = v + v2;", "plus and minus swapped"),
    ("src/qasm.cho", "                    la[top] = '(';\n                    top = top + 1;\n                    var m = 0;", "                    var m = 0;", "a parameter's value without its parentheses"),
    ("src/qasm.cho", "            la[0] = la[f + 2];\n            la[6] = la[f + 3];", "            la[0] = 32;\n            la[6] = la[f + 3];", "the saved character not restored at the end of a frame"),
    ("src/qasm.cho", "    if count > 7 {\n        return 0 - 2;\n    }", "    if count > 7 {\n        return w;\n    }", "a long name taken for its first seven characters"),
    ("src/qasm.cho", "    la[4] = la[4] + 1;\n    if la[4] > 200000 {", "    la[4] = la[4] + 0;\n    if la[4] > 200000 {", "the count of gate calls"),
    ("src/qasm.cho", "            la[top] = '0' + at % 10;", "            la[top] = '0' + at % 9;", "a qubit index digit"),
]


def gate_mutants(compiler, old):
    ok = True
    for path, a, b, what in GATE_MUTANTS:
        d = tempfile.mkdtemp(prefix="qasm-mut-")
        os.makedirs(os.path.join(d, "src"))
        for f in os.listdir(os.path.join(ROOT, "src")):
            text = open(os.path.join(ROOT, "src", f)).read()
            if "src/" + f == path:
                if text.count(a) != 1:
                    print(f"FAIL mutant '{what}': the text it changes occurs {text.count(a)} times")
                    ok = False
                    text = None
                else:
                    text = text.replace(a, b, 1)
            if text is not None:
                open(os.path.join(d, "src", f), "w").write(text)
        exe = os.path.join(d, "qsim")
        srcs = [os.path.join(d, "src", f) for f in sorted(os.listdir(os.path.join(d, "src"))) if f.endswith(".cho")]
        r = subprocess.run([compiler, "build", *srcs, "--std", "-o", exe], capture_output=True, text=True)
        if r.returncode:
            print(f"FAIL mutant '{what}' does not build: {r.stderr[-200:]}")
            ok = False
            continue
        import contextlib, io as _io
        with contextlib.redirect_stdout(_io.StringIO()):
            survived = check_gate_defs(exe, old)
        if survived:
            print(f"FAIL mutant '{what}' SURVIVED")
            ok = False
        else:
            print(f"ok   mutant killed: {what}")
    return ok


def check_print_options(exe):
    """`--quiet` and `--threshold P` (README of the benchmark: the printing of a dense state costs 17 microseconds an amplitude): with no flag the output is what it always was; `--threshold P` prints exactly the amplitude
    lines whose probability is at least P, in the same order, on 60 random circuits and four values of P, and keeps the measurement lines; `--quiet` prints none of the amplitudes; the arguments that are not these are refused with
    status 2 and nothing on standard output; a `.qc` circuit ignores both."""
    rng = np.random.default_rng(20261104)
    ok = bad = 0
    for case in range(60):
        n = int(rng.integers(2, 7))
        lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];", f"creg c[{n}];"]
        for _ in range(int(rng.integers(3, 12))):
            q = [int(x) for x in rng.permutation(n)]
            kind = str(rng.choice(["h", "t", "rx", "cx", "ry", "m"]))
            if kind in ("h", "t"):
                lines.append(f"{kind} q[{q[0]}];")
            elif kind in ("rx", "ry"):
                lines.append(f"{kind}({float(rng.uniform(-3, 3))!r}) q[{q[0]}];")
            elif kind == "cx":
                lines.append(f"cx q[{q[0]}],q[{q[1]}];")
            else:
                lines.append(f"measure q[{q[0]}] -> c[{q[0]}];")
        text = "\n".join(lines) + "\n"
        full = subprocess.run([exe], input=text, capture_output=True, text=True).stdout.splitlines()
        amps = [l for l in full if l.startswith("amp ")]
        others = [l for l in full if not l.startswith("amp ")]
        for P in ("0", "0.01", "0.2", "1"):
            got = subprocess.run([exe, "--threshold", P], input=text, capture_output=True, text=True).stdout.splitlines()
            want = others + [l for l in amps if P == "0" or float(l.split()[2]) ** 2 + float(l.split()[3]) ** 2 >= float(P)]
            good = sorted(got) == sorted(want) and [l for l in got if l.startswith("amp ")] == [l for l in want if l.startswith("amp ")] and (P != "0" or got == full)
            ok += good
            bad += not good
            if not good:
                print(f"FAIL --threshold {P}: {len(got)} lines against {len(want)}\n{text}")
        quiet = subprocess.run([exe, "--quiet"], input=text, capture_output=True, text=True).stdout.splitlines()
        good = quiet == others
        ok += good
        bad += not good
        if not good:
            print(f"FAIL --quiet printed {len(quiet)} lines, expected the {len(others)} that are not amplitudes\n{text}")
    # a basis state has probability exactly 1: `--threshold 1` keeps it
    one = subprocess.run([exe, "--threshold", "1"], input="OPENQASM 2.0;\nqreg q[2];\nx q[1];\n", capture_output=True, text=True).stdout
    good = one.splitlines() == ["amp 2 1e0 0e0"]
    ok += good
    bad += not good
    if not good:
        print(f"FAIL --threshold 1 on a basis state: {one!r}")
    for argv in (["--bogus"], ["--threshold"], ["--threshold", "x"], ["--threshold", "-1"], ["--threshold", "2"], ["--threshold", "nan"], ["--quiet", "extra"]):
        r = subprocess.run([exe, *argv], input="OPENQASM 2.0;\nqreg q[1];\nx q[0];\n", capture_output=True, text=True)
        good = r.returncode == 2 and r.stdout == ""
        ok += good
        bad += not good
        if not good:
            print(f"FAIL {argv} should be refused with status 2: {r.returncode} {r.stdout[:40]!r}")
    qc = subprocess.run([exe, "--quiet"], input="n 1\nx 0\n", capture_output=True, text=True).stdout
    good = qc.startswith("amp 0")
    ok += good
    bad += not good
    print(f"{'ok  ' if not bad else 'FAIL'} --quiet and --threshold: {ok} checks (60 random circuits x four thresholds, --quiet, the exact value 1, seven refusals, a .qc circuit that ignores them); {bad} wrong")
    return bad == 0


def ulps(a, b):
    import struct
    key = lambda x: (lambda i: i if i >= 0 else -(1 << 63) - i)(struct.unpack("<q", struct.pack("<d", x))[0])
    return abs(key(a) - key(b))


def number_cases(rng):
    """Decimal texts for the reader: Python's repr of random doubles (1 to 17 digits, every magnitude), random digit strings of 1 to 18 digits with a point and an exponent, and the exact halfway cases between two doubles."""
    out = []
    for _ in range(6000):
        x = float(rng.uniform(0.5, 1.0)) * 10.0 ** float(rng.integers(-12, 12)) * (1.0 + float(rng.integers(0, 2)) * 5.0)
        out.append(repr(x))
        out.append(repr(float(np.pi * rng.integers(-5000, 5000) / rng.integers(1, 200))).lstrip("-"))
    for _ in range(6000):
        nd = int(rng.integers(1, 19))
        digits = "".join(str(int(d)) for d in rng.integers(0, 10, nd))
        dot = int(rng.integers(0, nd + 1))
        text = digits[:dot] + "." + digits[dot:] if rng.random() < 0.8 else digits
        if rng.random() < 0.3:
            text += "e" + ("-" if rng.random() < 0.5 else "") + str(int(rng.integers(0, 25)))
        out.append(text)
    for k in range(53, 62):
        for odd in (1, 3, 5, 7):
            v = (1 << k) + odd * (1 << max(0, k - 53))
            out += [f"{v}.0", f"{v}.00", f"{v // 10}.{v % 10}", f"{v // 100}.{v % 100:02d}"]
            out += [f"{(1 << k) + (1 << max(0, k - 53)) // 2 + j}.0" for j in (-1, 0, 1)]
    return out


def check_numbers(compiler):
    """The decimal reader against Python's `float`, which is correctly rounded: bit for bit when the text is in the range the reader promises (at most 18 significant digits, and a power of ten of 18 below, or of 22 either way for digits below 2^53, or digits times the power below 2^62),
    within two units in the last place otherwise. Built apart from `qsim`: `tests/qasm/numbers.cho` prints what the reader made of each text."""
    from decimal import Decimal
    exe = os.path.join(tempfile.mkdtemp(prefix="qasm-num-"), "numbers")
    srcs = [os.path.join(ROOT, "src", f) for f in sorted(os.listdir(os.path.join(ROOT, "src"))) if f.endswith(".cho") and f != "main.cho"]
    subprocess.run([compiler, "build", *srcs, os.path.join(ROOT, "tests", "qasm", "numbers.cho"), "--std", "-o", exe], check=True)
    texts = number_cases(np.random.default_rng(20261028))
    r = subprocess.run([exe], input=" ".join(texts), capture_output=True, text=True)
    lines = r.stdout.splitlines()
    if len(lines) != len(texts) or r.returncode != 0:
        print(f"FAIL decimal reader: {len(lines)} answers for {len(texts)} texts, status {r.returncode}")
        return False
    exact = near = worst = bad = 0
    for text, line in zip(texts, lines):
        kind, whole, value = line.split()
        want = float(text)
        sign, digs, e10 = Decimal(text).as_tuple()
        # significant digits as the reader counts them: from the first non-zero one
        stripped = "".join(str(d) for d in digs).lstrip("0")
        m = int(stripped) if stripped else 0
        raw = text.lower().replace("e", " ").split()[0].replace(".", "").lstrip("0")
        in_range = len(raw) <= 18 and (-18 <= e10 <= 0 or (m < (1 << 53) and -22 <= e10 <= 22) or (0 < e10 <= 18 and m * 10 ** e10 < (1 << 62)))
        if len(raw) > 18 and not (-18 <= e10):
            in_range = False
        if kind == "0":
            bad += 1
            print(f"FAIL decimal reader refused {text!r}")
            continue
        got = float(value)
        d = ulps(got, want)
        if in_range:
            exact += 1
            if d != 0:
                bad += 1
                if bad < 8:
                    print(f"FAIL decimal reader: {text!r} gave {got!r}, Python {want!r} ({d} ulps)")
        else:
            near += 1
            worst = max(worst, d)
            if d > 2:
                bad += 1
                if bad < 8:
                    print(f"FAIL decimal reader: {text!r} gave {got!r}, Python {want!r} ({d} ulps; outside the exact range)")
    print(f"{'ok  ' if not bad else 'FAIL'} decimal reader: {exact} texts in its exact range are bit for bit Python's float, {near} outside it within {worst} ulp; {bad} wrong")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    ap.add_argument("--exe")
    ap.add_argument("--mutants", action="store_true", help="also build the reader with one deliberate bug at a time and require the gate-definition checks to fail on each")
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
    old = build_old(args.compiler)
    numbers = check_numbers(args.compiler) and check_decimal_circuits(exe) and check_controlled(exe) and check_classical(exe) and check_gate_defs(exe, old) and check_print_options(exe)
    if numbers and args.mutants:
        numbers = gate_mutants(args.compiler, old)
    sys.exit(1 if failed or not native or not numbers else 0)


if __name__ == "__main__":
    main()
