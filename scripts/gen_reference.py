#!/usr/bin/env python3
"""Generate the circuits in tests/diff/ and their Qiskit reference outputs.

Run from the repository root:  python3 scripts/gen_reference.py

For each circuit this writes `tests/diff/<name>.qc` (the input `qsim`
reads) and `tests/diff/<name>.ref` (what a correct simulator prints).

The reference is Qiskit's `Statevector`, one gate at a time, so that a
measurement can sit in the middle of a circuit. Conventions (docs/
qubit-types.md D5): qubit 0 is the least significant bit of the amplitude
index, which is Qiskit's. An angle is `math.pi * num / den`, evaluated in
that order, which is what `qsim` computes.

Measurement is checked against an independent implementation, not
copied from the simulator: the outcome is drawn with a Python copy of the
xorshift64* generator in src/measure.cho, from Qiskit's own probability
of the qubit reading 1, and the post-measurement state is Qiskit's
projection renormalised with numpy. If the two generators or the collapse
disagree, the diff fails.

`.ref` files are sparse: only amplitudes that are not exactly zero are
listed, because GHZ(20) has 2^20 amplitudes and two of them are not
zero. The checker treats a missing index as 0.
"""
import math
import os
import random
import sys

import numpy as np
import qiskit
from qiskit.circuit.library import CXGate, CZGate, HGate, RZGate, SGate, TGate, XGate, ZGate
from qiskit.quantum_info import Statevector

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "diff")
MASK = (1 << 64) - 1
DEFAULT_SEED = 88172645463325252


class Rng:
    """xorshift64*, the same generator as src/measure.cho."""

    def __init__(self, state=DEFAULT_SEED):
        self.state = state & MASK

    def next(self):
        x = self.state
        x ^= x >> 12
        x ^= (x << 25) & MASK
        x ^= x >> 27
        self.state = x
        y = (x * 2685821657736338717) & MASK
        return float(y >> 11) / 9007199254740992.0


def angle(num, den):
    return math.pi * num / den


def reference(n, ops):
    """Return the lines `qsim` must print for the circuit `ops`."""
    sv = Statevector.from_int(0, 2**n)
    rng = Rng()
    lines = []
    for op in ops:
        name, args = op[0], op[1:]
        if name in ("h", "x", "z", "s", "t"):
            gate = {"h": HGate, "x": XGate, "z": ZGate, "s": SGate, "t": TGate}[name]()
            sv = sv.evolve(gate, qargs=[args[0]])
        elif name == "cx":
            sv = sv.evolve(CXGate(), qargs=[args[0], args[1]])
        elif name == "cz":
            sv = sv.evolve(CZGate(), qargs=[args[0], args[1]])
        elif name == "rz":
            sv = sv.evolve(RZGate(angle(args[1], args[2])), qargs=[args[0]])
        elif name == "seed":
            rng = Rng(args[0])
        elif name == "trig":
            half = angle(args[0], args[1]) * 0.5
            lines.append(f"trig {math.cos(half)!r} {math.sin(half)!r}")
        elif name == "m":
            q = args[0]
            p1 = float(sv.probabilities([q])[1])
            bit = 1 if rng.next() < p1 else 0
            data = np.array(sv.data)
            idx = np.arange(len(data))
            keep = ((idx >> q) & 1) == bit
            data = np.where(keep, data, 0)
            data = data / np.linalg.norm(data)
            sv = Statevector(data)
            lines.append(f"m {q} {bit}")
        else:
            raise ValueError(name)
    for i, a in enumerate(sv.data):
        if a != 0:
            lines.append(f"amp {i} {float(a.real)!r} {float(a.imag)!r}")
    return lines


def render(n, ops):
    out = [f"n {n}"]
    for op in ops:
        out.append(" ".join(str(a) for a in op))
    return "\n".join(out) + "\n"


def random_circuit(rng, n, count):
    ops = []
    for _ in range(count):
        kind = rng.choice(["h", "x", "z", "s", "t", "cx", "cz", "rz", "rz"])
        if kind in ("cx", "cz"):
            a, b = rng.sample(range(n), 2)
            ops.append((kind, a, b))
        elif kind == "rz":
            ops.append((kind, rng.randrange(n), rng.randrange(-40, 41), rng.choice([3, 4, 5, 7, 8, 16])))
        else:
            ops.append((kind, rng.randrange(n)))
    return ops


def circuits():
    c = {}
    c["bell"] = (2, [("h", 0), ("cx", 0, 1)])
    for k in range(3, 11):
        c[f"ghz{k}"] = (k, [("h", 0)] + [("cx", i, i + 1) for i in range(k - 1)])
    # n = 20: two non-zero amplitudes out of 2^20.
    c["ghz20"] = (20, [("h", 0)] + [("cx", i, i + 1) for i in range(19)])
    # Every gate once, then a long random tail: the gates against each other.
    c["every_gate"] = (3, [("h", 0), ("h", 1), ("h", 2), ("x", 0), ("z", 1), ("s", 2), ("t", 0),
                           ("cx", 0, 1), ("cz", 1, 2), ("rz", 2, 1, 3), ("h", 2), ("t", 1)])
    c["random5"] = (5, random_circuit(random.Random(20260101), 5, 60))
    c["random8"] = (8, random_circuit(random.Random(20260102), 8, 120))
    c["random12"] = (12, random_circuit(random.Random(20260103), 12, 160))
    # RZ over a wide range of angles. After H the state is sensitive to the phase.
    sweep = [("h", 0)]
    for num in (1, -1, 7, 31, 100, 997, -12345, 99991, 500000, -999983):
        for den in (1, 3, 8, 97):
            sweep.append(("rz", 0, num, den))
            sweep.append(("h", 0))
    c["rz_sweep"] = (1, sweep)
    # sin/cos in isolation: the angles RZ asks for, printed without a state.
    trig = [("trig", num, den) for num in (1, 3, 7, 31, 100, 997, 12345, 99991, 500000, 999983, 4000000)
            for den in (1, 2, 3, 5, 8, 16, 97)]
    c["trig"] = (1, trig)
    # Measurement: the sampler and the collapse.
    c["measure_bell"] = (2, [("seed", 7), ("h", 0), ("cx", 0, 1), ("m", 0), ("m", 1)])
    c["measure_ghz5"] = (5, [("seed", 2026), ("h", 0)] + [("cx", i, i + 1) for i in range(4)] + [("m", 2), ("m", 0)])
    c["measure_random6"] = (6, [("seed", 99)] + random_circuit(random.Random(5), 6, 40)
                            + [("m", 3), ("h", 3), ("m", 3), ("m", 0), ("m", 5)])
    # The same circuit under two seeds, to see that the seed matters.
    for seed in (1, 2, 3, 4, 5, 6):
        c[f"measure_seed{seed}"] = (3, [("seed", seed), ("h", 0), ("h", 1), ("h", 2), ("m", 0), ("m", 1), ("m", 2)])
    return c


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (n, ops) in circuits().items():
        with open(os.path.join(OUT, name + ".qc"), "w") as f:
            f.write(render(n, ops))
        with open(os.path.join(OUT, name + ".ref"), "w") as f:
            f.write(f"# qiskit {qiskit.__version__}, numpy {np.__version__}\n")
            f.write("\n".join(reference(n, ops)) + "\n")
    print(f"wrote {len(circuits())} circuits to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
