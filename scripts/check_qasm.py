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
    for angle in ("1e", "pi*", ".", "abc", "1/0", "1e50", "1..2", "-", "pi/", "2*3"):
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
    numbers = check_numbers(args.compiler) and check_decimal_circuits(exe) and check_controlled(exe) and check_classical(exe)
    sys.exit(1 if failed or not native or not numbers else 0)


if __name__ == "__main__":
    main()
