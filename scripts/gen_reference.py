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
from qiskit.circuit.library import (CCXGate, CPhaseGate, CXGate, CZGate, HGate, PhaseGate, RXGate, RYGate, RZGate,
                                    SdgGate, SGate, SwapGate, TdgGate, TGate, XGate, YGate, ZGate)
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
        if name in ("h", "x", "y", "z", "s", "t", "sdg", "tdg"):
            gate = {"h": HGate, "x": XGate, "y": YGate, "z": ZGate, "s": SGate, "t": TGate, "sdg": SdgGate, "tdg": TdgGate}[name]()
            sv = sv.evolve(gate, qargs=[args[0]])
        elif name == "swap":
            sv = sv.evolve(SwapGate(), qargs=[args[0], args[1]])
        elif name == "ccx":
            sv = sv.evolve(CCXGate(), qargs=[args[0], args[1], args[2]])
        elif name in ("rx", "ry", "p"):
            gate = {"rx": RXGate, "ry": RYGate, "p": PhaseGate}[name](angle(args[1], args[2]))
            sv = sv.evolve(gate, qargs=[args[0]])
        elif name == "cp":
            sv = sv.evolve(CPhaseGate(angle(args[2], args[3])), qargs=[args[0], args[1]])
        elif name == "sample":
            # An independent method: a cumulative sum and a binary search, where
            # the simulator adds up probabilities one state at a time.
            probs = np.abs(np.array(sv.data)) ** 2
            cum = np.cumsum(probs)
            last = int(np.nonzero(probs)[0][-1])
            picks = []
            for _ in range(args[0]):
                u = rng.next()
                k = int(np.searchsorted(cum, u, side="right"))
                picks.append(k if k < len(cum) and probs[k] > 0 else last)
            for k in sorted(set(picks)):
                lines.append(f"sample {k:0{n}b} {picks.count(k)}")
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


def feature_circuits():
    """Circuits that use the gates and `sample` added after M3: algorithms with a known answer."""
    c = {}
    c["gates_extra"] = (3, [("h", 0), ("y", 1), ("rx", 0, 1, 3), ("ry", 2, 2, 5), ("p", 1, 1, 7), ("sdg", 0), ("tdg", 1),
                            ("swap", 0, 2), ("cp", 1, 2, 3, 8), ("ccx", 0, 1, 2), ("h", 1), ("rx", 2, -3, 4)])
    c["toffoli"] = (3, [("x", 0), ("x", 1), ("ccx", 0, 1, 2)])
    c["rx_ry_sweep"] = (1, [op for k in (1, 3, 7, 11, 31, 100) for op in (("rx", 0, k, 5), ("ry", 0, -k, 7), ("p", 0, k, 3))])
    # Quantum Fourier transform of |5> on 4 qubits (QFT = H and controlled phases, then reversal).
    qft = [("x", 0), ("x", 2)]
    for j in range(3, -1, -1):
        qft.append(("h", j))
        for k in range(j - 1, -1, -1):
            qft.append(("cp", k, j, 1, 2 ** (j - k)))
    qft += [("swap", 0, 3), ("swap", 1, 2)]
    c["qft4"] = (4, qft)
    # Grover on 3 qubits, marked item 101 (= 5), two iterations. After them the marked
    # item has probability about 0.945; `sample` shows it.
    g = [("h", q) for q in range(3)]
    for _ in range(2):
        g += [("x", 1), ("h", 2), ("ccx", 0, 1, 2), ("h", 2), ("x", 1)]       # oracle: phase-flip |101>
        g += [("h", q) for q in range(3)] + [("x", q) for q in range(3)]       # diffuser
        g += [("h", 2), ("ccx", 0, 1, 2), ("h", 2)]
        g += [("x", q) for q in range(3)] + [("h", q) for q in range(3)]
    g += [("seed", 2026), ("sample", 1000)]
    c["grover3"] = (3, g)
    # Bernstein-Vazirani, secret 1011 on 4 qubits plus an ancilla (qubit 4).
    bv = [("x", 4)] + [("h", q) for q in range(5)] + [("cx", q, 4) for q in range(4) if (0b1011 >> q) & 1]
    bv += [("h", q) for q in range(4)] + [("seed", 7), ("sample", 200)]
    c["bernstein_vazirani"] = (5, bv)
    # Deutsch-Jozsa, a balanced oracle (parity of qubits 0 and 2) on 3 qubits plus an ancilla.
    dj = [("x", 3)] + [("h", q) for q in range(4)] + [("cx", 0, 3), ("cx", 2, 3)] + [("h", q) for q in range(3)]
    dj += [("seed", 11), ("sample", 100)]
    c["deutsch_jozsa"] = (4, dj)
    c["ghz5_sample"] = (5, [("h", 0)] + [("cx", i, i + 1) for i in range(4)] + [("seed", 5), ("sample", 500)])
    return c


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
    c.update(feature_circuits())
    # The unitary half of teleportation (the landing page steps through it):
    # prepare a state on qubit 0, entangle 1 and 2, then rotate 0 and 1 into the Bell basis.
    c["teleport_unitary"] = (3, [("h", 0), ("rz", 0, 1, 3), ("h", 1), ("cx", 1, 2), ("cx", 0, 1), ("h", 0)])
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
