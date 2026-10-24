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


ONE_Q = ("h", "x", "y", "z", "s", "t", "sdg", "tdg", "rx", "ry", "rz", "p")
TWO_Q = ("cx", "cz", "cp", "swap")
PAULI = {1: XGate, 2: YGate, 3: ZGate}


class NoiseState:
    """The noise parameters a circuit sets, with the same override rules as src/profile.cho."""

    def __init__(self):
        self.ro = self.m1 = self.m2 = 0.0
        self.g1, self.g2, self.rop = {}, {}, {}
        self.coh, self.gt1, self.gt2 = {}, 0, 0
        self.dur1, self.dur2 = {}, {}

    def set(self, name, a):
        frac = lambda x, y: x / y if x else 0.0
        if name == "readout":
            self.ro = frac(a[0], a[1])
        elif name == "model1":
            self.m1 = frac(a[0], a[1])
        elif name == "model2":
            self.m2 = frac(a[0], a[1])
        elif name == "gate1err":
            self.g1[a[0]] = frac(a[1], a[2])
        elif name == "gate2err":
            self.g2[frozenset((a[0], a[1]))] = frac(a[2], a[3])
        elif name == "readerr":
            self.rop[a[0]] = (frac(a[1], a[2]), frac(a[3], a[4]))
        elif name == "coher":
            self.coh[a[0]] = (a[1], a[2])
        elif name == "time1":
            self.gt1 = a[0]
        elif name == "time2":
            self.gt2 = a[0]
        elif name == "dur1":
            self.dur1[a[0]] = a[1]
        elif name == "dur2":
            self.dur2[frozenset((a[0], a[1]))] = a[2]

    def t1q(self, q):
        return self.dur1[q] if self.dur1.get(q, 0) > 0 else self.gt1

    def t2q(self, a, b):
        v = self.dur2.get(frozenset((a, b)), 0)
        return v if v > 0 else self.gt2

    def relax_params(self, q, ns):
        """(gamma, flip probability) for qubit q idling ns nanoseconds, or None without a `coher`."""
        if ns <= 0 or q not in self.coh:
            return None
        t1, t2 = self.coh[q]
        rate = 1.0 / t2 - 0.5 / t1
        return 1.0 - math.exp(-ns / t1), (0.5 * (1.0 - math.exp(-ns * rate)) if rate > 0.0 else 0.0)

    def g1p(self, q):
        return self.g1[q] if q in self.g1 else self.m1

    def g2p(self, a, b):
        key = frozenset((a, b))
        return self.g2[key] if key in self.g2 else self.m2

    def rp(self, q, bit):
        return self.rop[q][bit] if q in self.rop else self.ro


NOISE_SET = ("readout", "model1", "model2", "gate1err", "gate2err", "readerr", "coher", "time1", "time2", "dur1", "dur2")


def pauli_pair(sv, a, b, m):
    """Apply Pauli P (m // 4) on qubit a and Q (m % 4) on qubit b; 0 is the identity."""
    for q, k in ((a, m // 4), (b, m % 4)):
        if k:
            sv = sv.evolve(PAULI[k](), qargs=[q])
    return sv


def traj_ampdamp(sv, q, p, u):
    """One amplitude-damping trajectory with decay probability p and draw u (src/noise.cho)."""
    p1 = p * float(sv.probabilities([q])[1])
    if u < p1:
        k1 = np.array([[0, math.sqrt(p) / math.sqrt(p1)], [0, 0]], dtype=complex)
        return sv.evolve(Operator(k1), qargs=[q])
    keep = 1.0 / math.sqrt(1.0 - p1)
    k0 = np.array([[keep, 0], [0, math.sqrt(1.0 - p) * keep]], dtype=complex)
    return sv.evolve(Operator(k0), qargs=[q])


def traj_relax(sv, rng, ns, q, ns_ns):
    """Idle qubit q for ns_ns nanoseconds: damping then a phase flip, two draws (none without a coher)."""
    par = ns.relax_params(q, ns_ns)
    if par is None:
        return sv
    sv = traj_ampdamp(sv, q, par[0], rng.next())
    if rng.next() < par[1]:
        sv = sv.evolve(ZGate(), qargs=[q])
    return sv


def reference(n, ops):
    """Return the lines `qsim` must print for the circuit `ops`."""
    sv = Statevector.from_int(0, 2**n)
    rng = Rng()
    lines = []
    ns = NoiseState()
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
                sv = traj_ampdamp(sv, q, p, u)
        elif name == "depol2":
            a, b, p = args[0], args[1], args[2] / args[3]
            u = rng.next()
            if u < p:
                sv = pauli_pair(sv, a, b, min(int(u / p * 15.0), 14) + 1)
        elif name in NOISE_SET:
            ns.set(name, args)
        elif name == "wait":
            sv = traj_relax(sv, rng, ns, args[0], args[1])
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
                pick = k if k < len(cum) and probs[k] > 0 else last
                reported = pick
                for qq in range(n):
                    pr = ns.rp(qq, (pick >> qq) & 1)
                    if pr > 0.0 and rng.next() < pr:
                        reported ^= 1 << qq
                picks.append(reported)
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
            reported = bit
            if ns.rp(q, bit) > 0.0 and rng.next() < ns.rp(q, bit):
                reported = 1 - bit
            data = np.array(sv.data)
            idx = np.arange(len(data))
            keep = ((idx >> q) & 1) == bit
            data = np.where(keep, data, 0)
            data = data / np.linalg.norm(data)
            sv = Statevector(data)
            lines.append(f"m {q} {reported}")
        else:
            raise ValueError(name)
        # The gate-noise model: after a gate, depolarizing noise, one draw each.
        if name in ONE_Q and ns.g1p(args[0]) > 0.0:
            p1 = ns.g1p(args[0])
            u = rng.next()
            if u < p1:
                k = u / p1
                sv = sv.evolve((XGate() if k < 1.0 / 3.0 else (YGate() if k < 2.0 / 3.0 else ZGate())), qargs=[args[0]])
        if name in TWO_Q and ns.g2p(args[0], args[1]) > 0.0:
            p2 = ns.g2p(args[0], args[1])
            u = rng.next()
            if u < p2:
                sv = pauli_pair(sv, args[0], args[1], min(int(u / p2 * 15.0), 14) + 1)
        if name in ONE_Q:
            sv = traj_relax(sv, rng, ns, args[0], ns.t1q(args[0]))
        if name in TWO_Q:
            sv = traj_relax(sv, rng, ns, args[0], ns.t2q(args[0], args[1]))
            sv = traj_relax(sv, rng, ns, args[1], ns.t2q(args[0], args[1]))
    for i, a in enumerate(sv.data):
        if a != 0:
            lines.append(f"amp {i} {float(a.real)!r} {float(a.imag)!r}")
    return lines


def dm_relax(rho, ns, q, ns_ns):
    """Qiskit Aer's own thermal-relaxation channel: the check on `coher`, built from T1, T2 and the time."""
    from qiskit.quantum_info import Kraus
    from qiskit_aer.noise import thermal_relaxation_error
    if ns_ns <= 0 or q not in ns.coh:
        return rho
    t1, t2 = ns.coh[q]
    return rho.evolve(Kraus(thermal_relaxation_error(t1, t2, ns_ns)), qargs=[q])


def reference_dm(n, ops):
    """The lines `qsim` must print for a `dm <n>` circuit: Qiskit's DensityMatrix, exact."""
    from noise_lib import kraus
    from qiskit.quantum_info import DensityMatrix, Kraus
    rho = DensityMatrix.from_int(0, 2**n)
    rng = Rng()
    lines, quiet = [], False
    ns = NoiseState()

    def depol2_kraus(p):
        P = [np.eye(2, dtype=complex), np.array([[0, 1], [1, 0]], dtype=complex),
             np.array([[0, -1j], [1j, 0]], dtype=complex), np.array([[1, 0], [0, -1]], dtype=complex)]
        ks = [math.sqrt(1 - p) * np.eye(4, dtype=complex)]
        for m in range(1, 16):
            ks.append(math.sqrt(p / 15) * np.kron(P[m % 4], P[m // 4]))   # qargs [a, b]: b is the high factor
        return ks

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
        elif name == "depol2":
            rho = rho.evolve(Kraus(depol2_kraus(a[2] / a[3])), qargs=[a[0], a[1]])
        elif name in NOISE_SET:
            ns.set(name, a)
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
            reported = bit
            if ns.rp(q, bit) > 0.0 and rng.next() < ns.rp(q, bit):
                reported = 1 - bit
            lines.append(f"m {q} {reported}")
        elif name == "wait":
            rho = dm_relax(rho, ns, a[0], a[1])
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
        if name in ONE_Q and ns.g1p(a[0]) > 0.0:
            rho = rho.evolve(Kraus(kraus("depol", ns.g1p(a[0]))), qargs=[a[0]])
        if name in TWO_Q and ns.g2p(a[0], a[1]) > 0.0:
            rho = rho.evolve(Kraus(depol2_kraus(ns.g2p(a[0], a[1]))), qargs=[a[0], a[1]])
        if name in ONE_Q:
            rho = dm_relax(rho, ns, a[0], ns.t1q(a[0]))
        if name in TWO_Q:
            rho = dm_relax(rho, ns, a[0], ns.t2q(a[0], a[1]))
            rho = dm_relax(rho, ns, a[1], ns.t2q(a[0], a[1]))
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


# An invented example device (the numbers are made up, not from a real machine): per-qubit
# one-qubit-gate errors, per-pair two-qubit errors, asymmetric readout on two qubits.
PROFILE = [("model1", 1, 100), ("gate1err", 0, 1, 15), ("gate1err", 2, 1, 6), ("gate2err", 0, 1, 1, 7), ("gate2err", 2, 1, 1, 9),
           ("readerr", 0, 1, 12, 1, 6), ("readerr", 1, 1, 30, 1, 5), ("readout", 1, 25)]


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
    for k in range(1, 5):
        c[f"noise_model_seed{k}"] = (3, [("seed", k), ("model1", 1, 10), ("model2", 1, 8), ("h", 0), ("cx", 0, 1), ("cx", 1, 2),
                                         ("ry", 2, 1, 3), ("readout", 1, 5), ("m", 0), ("sample", 200)])
    for k in range(1, 4):
        c[f"depol2_seed{k}"] = (3, [("seed", k), ("h", 0), ("cx", 0, 1), ("depol2", 0, 1, 1, 3), ("ry", 2, 1, 5),
                                    ("depol2", 1, 2, 1, 2), ("depol2", 2, 0, 1, 4)])
    for k in range(1, 5):
        c[f"profile_seed{k}"] = (3, [("seed", k)] + PROFILE + [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("ry", 2, 1, 3), ("rz", 1, 1, 5), ("cx", 2, 0),
                                                            ("m", 0), ("m", 1), ("sample", 300)])
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
    c["dm_depol2"] = (3, [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("depol2", 0, 1, 1, 5), ("depol2", 1, 2, 1, 4), ("depol2", 2, 0, 1, 3),
                          ("purity",), ("trace",)])
    c["dm_model"] = (3, [("model1", 1, 20), ("model2", 1, 10), ("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("rz", 2, 1, 4), ("swap", 0, 2),
                         ("cp", 0, 1, 1, 3), ("purity",), ("probs",)])
    c["dm_readout"] = (2, [("seed", 3), ("readout", 1, 4), ("h", 0), ("cx", 0, 1), ("m", 0), ("m", 1), ("purity",)])
    c["dm_profile"] = (3, [("seed", 9)] + PROFILE + [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("ry", 2, 1, 3), ("rz", 1, 1, 5), ("cx", 2, 0),
                                                  ("m", 0), ("m", 1), ("purity",), ("probs",)])
    IDLE = [("coher", 0, 50000, 70000), ("coher", 1, 30000, 20000), ("coher", 2, 40000, 80000), ("time1", 35), ("time2", 300), ("dur2", 0, 1, 520), ("dur1", 2, 50)]
    c["dm_idle_t1"] = (1, [("coher", 0, 50000, 70000), ("x", 0), ("wait", 0, 20000), ("probs",), ("purity",)])
    c["dm_idle_ramsey"] = (1, [("coher", 0, 50000, 70000), ("h", 0), ("wait", 0, 30000), ("h", 0), ("probs",)])
    c["dm_idle_t2max"] = (1, [("coher", 0, 40000, 80000), ("h", 0), ("wait", 0, 40000), ("purity",)])
    c["dm_idle_gates"] = (3, IDLE + [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("ry", 2, 1, 3), ("swap", 0, 2), ("wait", 1, 5000),
                                     ("purity",), ("probs",)])
    c["dm_idle_nocoher"] = (2, [("time1", 1000), ("wait", 0, 1000), ("h", 0), ("cx", 0, 1), ("purity",)])
    c["dm_idle_model"] = (3, IDLE + [("model1", 1, 100), ("model2", 1, 40), ("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("purity",), ("probs",)])
    for k in range(1, 5):
        c[f"idle_seed{k}"] = (3, [("seed", k)] + IDLE + [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("wait", 0, 15000), ("wait", 2, 9000),
                                                        ("ry", 2, 1, 3), ("cx", 2, 0), ("m", 0), ("m", 1), ("sample", 50)])
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
