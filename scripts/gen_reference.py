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
from qiskit.quantum_info import Operator, Statevector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
        elif name in ("bitflip", "phaseflip", "depol", "ampdamp"):
            # Quantum trajectories, as in src/noise.cho: one draw per channel; a
            # Kraus operator is chosen with its probability and the state renormalised.
            q, p = args[0], args[1] / args[2]
            u = rng.next()
            if name == "bitflip" and u < p:
                sv = sv.evolve(XGate(), qargs=[q])
            elif name == "phaseflip" and u < p:
                sv = sv.evolve(ZGate(), qargs=[q])
            elif name == "depol" and u < p:
                k = u / p
                gate = XGate() if k < 1.0 / 3.0 else (YGate() if k < 2.0 / 3.0 else ZGate())
                sv = sv.evolve(gate, qargs=[q])
            elif name == "ampdamp":
                p1 = p * float(sv.probabilities([q])[1])
                if u < p1:
                    k1 = np.array([[0, math.sqrt(p) / math.sqrt(p1)], [0, 0]], dtype=complex)
                    sv = sv.evolve(Operator(k1), qargs=[q])
                else:
                    keep = 1.0 / math.sqrt(1.0 - p1)
                    k0 = np.array([[keep, 0], [0, math.sqrt(1.0 - p) * keep]], dtype=complex)
                    sv = sv.evolve(Operator(k0), qargs=[q])
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


def reference_dm(n, ops):
    """The lines `qsim` must print for a `dm <n>` circuit: Qiskit's DensityMatrix, exact."""
    from noise_lib import kraus
    from qiskit.quantum_info import DensityMatrix, Kraus
    rho = DensityMatrix.from_int(0, 2**n)
    rng = Rng()
    lines, quiet = [], False
    for name, *a in ops:
        if name in ("h", "x", "y", "z", "s", "t", "sdg", "tdg"):
            gate = {"h": HGate, "x": XGate, "y": YGate, "z": ZGate, "s": SGate, "t": TGate, "sdg": SdgGate, "tdg": TdgGate}[name]()
            rho = rho.evolve(Operator(gate), qargs=[a[0]])
        elif name in ("rx", "ry", "rz", "p"):
            gate = {"rx": RXGate, "ry": RYGate, "rz": RZGate, "p": PhaseGate}[name](angle(a[1], a[2]))
            rho = rho.evolve(Operator(gate), qargs=[a[0]])
        elif name in ("cx", "cz", "swap"):
            rho = rho.evolve(Operator({"cx": CXGate, "cz": CZGate, "swap": SwapGate}[name]()), qargs=[a[0], a[1]])
        elif name == "ccx":
            rho = rho.evolve(Operator(CCXGate()), qargs=[a[0], a[1], a[2]])
        elif name == "cp":
            rho = rho.evolve(Operator(CPhaseGate(angle(a[2], a[3]))), qargs=[a[0], a[1]])
        elif name in ("bitflip", "phaseflip", "depol", "ampdamp"):
            rho = rho.evolve(Kraus(kraus(name, a[1] / a[2])), qargs=[a[0]])
        elif name == "seed":
            rng = Rng(a[0])
        elif name == "m":
            q = a[0]
            m = rho.data
            diag = np.real(np.diag(m))
            p1 = float(sum(diag[i] for i in range(2**n) if (i >> q) & 1))
            u = rng.next()
            bit, pr = (1, p1) if u < p1 else (0, 1.0 - p1)
            keep = np.array([((i >> q) & 1) == bit for i in range(2**n)])
            m = m * np.outer(keep, keep) / pr
            rho = DensityMatrix(m)
            lines.append(f"m {q} {bit}")
        elif name == "purity":
            lines.append(f"purity {float(np.real(np.trace(rho.data @ rho.data)))!r}")
        elif name == "trace":
            lines.append(f"trace {float(np.real(np.trace(rho.data)))!r}")
        elif name == "probs":
            for i, pv in enumerate(np.real(np.diag(rho.data))):
                if pv > 0:
                    lines.append(f"prob {i:0{n}b} {float(pv)!r}")
        elif name == "quiet":
            quiet = True
        else:
            raise ValueError(name)
    if not quiet:
        for i in range(2**n):
            for j in range(2**n):
                v = rho.data[i, j]
                if v != 0:
                    lines.append(f"rho {i} {j} {float(v.real)!r} {float(v.imag)!r}")
    return lines


def render(n, ops, dm=False):
    out = [f"dm {n}" if dm else f"n {n}"]
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
    body = [("h", 0), ("cx", 0, 1), ("ry", 0, 1, 3), ("depol", 0, 1, 2), ("ampdamp", 1, 1, 2),
            ("bitflip", 0, 1, 2), ("phaseflip", 1, 1, 2), ("depol", 1, 1, 3)]
    for k in range(1, 9):
        c[f"noise_seed{k}"] = (2, [("seed", k)] + body)
    c["noise_p0"] = (2, [op if op[0] in ("h", "cx", "ry") else (op[0], op[1], 0, 1) for op in body])
    c["noise_p1"] = (2, [op if op[0] in ("h", "cx", "ry") else (op[0], op[1], 1, 1) for op in body])
    c["noise_ghz4"] = (4, [("seed", 21), ("h", 0)] + [op for i in range(3) for op in (("cx", i, i + 1), ("depol", i + 1, 1, 5))]
                       + [("ampdamp", 3, 1, 4), ("sample", 300)])
    c["ghz5_sample"] = (5, [("h", 0)] + [("cx", i, i + 1) for i in range(4)] + [("seed", 5), ("sample", 500)])
    return c


def density_circuits():
    """Circuits for the density-matrix mode (`dm <n>`): exact noise, compared with Qiskit's DensityMatrix."""
    c = {}
    c["dm_bell_depol"] = (2, [("h", 0), ("cx", 0, 1), ("depol", 1, 1, 4), ("purity",), ("trace",), ("probs",)])
    c["dm_every_gate"] = (3, [("h", 0), ("y", 1), ("rx", 0, 1, 3), ("ry", 2, 2, 5), ("p", 1, 1, 7), ("sdg", 0), ("tdg", 1), ("s", 2), ("t", 0),
                              ("swap", 0, 2), ("cp", 1, 2, 3, 8), ("ccx", 0, 1, 2), ("cz", 0, 1), ("cx", 2, 0), ("rz", 1, -5, 6), ("z", 2), ("x", 1),
                              ("purity",), ("trace",)])
    c["dm_channels3"] = (3, [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("depol", 0, 1, 6), ("ampdamp", 1, 1, 4), ("phaseflip", 2, 1, 5),
                             ("bitflip", 1, 1, 7), ("ry", 2, 1, 4), ("depol", 2, 1, 3), ("purity",), ("trace",)])
    c["dm_ampdamp"] = (2, [("h", 0), ("ampdamp", 0, 1, 3), ("cx", 0, 1), ("ampdamp", 1, 1, 2), ("probs",)])
    c["dm_measure"] = (2, [("seed", 3), ("h", 0), ("cx", 0, 1), ("depol", 0, 1, 5), ("m", 0), ("purity",), ("trace",)])
    qft = [("x", 0), ("x", 2)]
    for j in range(2, -1, -1):
        qft.append(("h", j))
        for k in range(j - 1, -1, -1):
            qft.append(("cp", k, j, 1, 2 ** (j - k)))
        qft.append(("depol", j, 1, 20))
    c["dm_qft3_noisy"] = (3, qft + [("swap", 0, 2), ("purity",)])
    c["dm_ghz4_noise"] = (4, [("h", 0)] + [op for i in range(3) for op in (("cx", i, i + 1), ("depol", i + 1, 1, 8))] + [("purity",), ("probs",)])
    rng = random.Random(77)
    ops = []
    for _ in range(40):
        kind = rng.choice(["h", "x", "y", "s", "t", "cx", "rz", "ry", "depol", "bitflip", "phaseflip", "ampdamp"])
        if kind == "cx":
            a, b = rng.sample(range(4), 2)
            ops.append((kind, a, b))
        elif kind in ("rz", "ry"):
            ops.append((kind, rng.randrange(4), rng.randrange(-9, 10), rng.choice([3, 5, 7])))
        elif kind in ("depol", "bitflip", "phaseflip", "ampdamp"):
            ops.append((kind, rng.randrange(4), rng.randrange(0, 6), 10))
        else:
            ops.append((kind, rng.randrange(4)))
    c["dm_random4"] = (4, ops + [("purity",), ("trace",)])
    c["dm_p0"] = (2, [("h", 0), ("cx", 0, 1), ("depol", 0, 0, 1), ("bitflip", 1, 0, 1), ("phaseflip", 0, 0, 1), ("ampdamp", 1, 0, 1), ("purity",)])
    c["dm_p1"] = (2, [("h", 0), ("cx", 0, 1), ("depol", 0, 1, 1), ("bitflip", 1, 1, 1), ("phaseflip", 0, 1, 1), ("ampdamp", 1, 1, 1), ("purity",), ("probs",)])
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
    c.update(density_circuits())
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
            f.write(render(n, ops, dm=name.startswith("dm_")))
        with open(os.path.join(OUT, name + ".ref"), "w") as f:
            f.write(f"# qiskit {qiskit.__version__}, numpy {np.__version__}\n")
            f.write("\n".join((reference_dm if name.startswith("dm_") else reference)(n, ops)) + "\n")
    print(f"wrote {len(circuits())} circuits to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
