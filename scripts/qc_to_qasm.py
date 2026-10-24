#!/usr/bin/env python3
"""Write each circuit in tests/diff/ that OpenQASM 2.0 can express as tests/qasm/<name>.qasm.

    python3 scripts/qc_to_qasm.py

Skipped: circuits with `seed`, `sample`, `trig` or noise (QASM has no such statements), and density-matrix circuits.
`swap` becomes three `cx`. `p` and `cp` are written `u1` and `cu1`, the names `qelib1.inc` defines.
Angles are written as `num*pi/den`, the form `src/qasm.cho` reads and Qiskit
evaluates to the same double. A measurement becomes `measure q[i] -> c[i];`.
"""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIFF = os.path.join(ROOT, "tests", "diff")
OUT = os.path.join(ROOT, "tests", "qasm")


def frac(num, den):
    mag = abs(num)
    if mag == 0:
        return "0"
    body = "pi" if mag == 1 else f"{mag}*pi"
    if den != 1:
        body += f"/{den}"
    return ("-" if num < 0 else "") + body


def convert(name):
    lines = [l.split() for l in open(os.path.join(DIFF, name + ".qc")) if l.strip()]
    if lines[0][0] != "n":
        return None          # a density-matrix circuit
    n = int(lines[0][1])
    out = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];", f"creg c[{n}];"]
    for op in lines[1:]:
        k, a = op[0], [int(x) for x in op[1:]]
        if k in ("seed", "sample", "trig", "quiet", "bitflip", "phaseflip", "depol", "ampdamp", "depol2", "readout", "model1", "model2"):
            return None
        if k in ("h", "x", "y", "z", "s", "t", "sdg", "tdg"):
            out.append(f"{k} q[{a[0]}];")
        elif k in ("cx", "cz"):
            out.append(f"{k} q[{a[0]}],q[{a[1]}];")
        elif k == "swap":
            # qelib1.inc has no swap: three CNOTs, which is what it means.
            out += [f"cx q[{a[0]}],q[{a[1]}];", f"cx q[{a[1]}],q[{a[0]}];", f"cx q[{a[0]}],q[{a[1]}];"]
        elif k == "ccx":
            out.append(f"ccx q[{a[0]}],q[{a[1]}],q[{a[2]}];")
        elif k in ("rx", "ry", "rz", "p"):
            # `p` is written `u1`: qelib1.inc defines u1 and cu1, not p and cp.
            out.append(f"{'u1' if k == 'p' else k}({frac(a[1], a[2])}) q[{a[0]}];")
        elif k == "cp":
            out.append(f"cu1({frac(a[2], a[3])}) q[{a[0]}],q[{a[1]}];")
        elif k == "m":
            out.append(f"measure q[{a[0]}] -> c[{a[0]}];")
        else:
            raise ValueError(k)
    return "\n".join(out) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    count = 0
    for f in sorted(os.listdir(DIFF)):
        if f.endswith(".qc"):
            text = convert(f[:-3])
            if text is not None:
                open(os.path.join(OUT, f[:-3] + ".qasm"), "w").write(text)
                count += 1
    print(f"wrote {count} circuits to {OUT}")


if __name__ == "__main__":
    main()
