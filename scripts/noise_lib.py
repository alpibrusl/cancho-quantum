"""Shared by check_noise.py and noise_curve.py: exact noisy evolution and trajectory ensembles.

The exact side is a density-matrix calculation from Kraus operators, written
independently of how `src/noise.cho` works: it never samples, and it applies a
channel as rho -> sum_k K rho K^dagger, which is the definition. The
trajectory side runs `qsim` once per seed and averages |psi><psi|.
"""
import concurrent.futures as cf
import math
import subprocess

import numpy as np
from qiskit.circuit.library import CXGate, CZGate, HGate, RYGate, RZGate, XGate, YGate, ZGate
from qiskit.quantum_info import DensityMatrix, Kraus, Operator
from qiskit_aer.noise import thermal_relaxation_error

I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)


def kraus(name, p):
    """The Kraus operators of each channel, from the textbook definitions."""
    if name == "bitflip":
        return [math.sqrt(1 - p) * I2, math.sqrt(p) * X]
    if name == "phaseflip":
        return [math.sqrt(1 - p) * I2, math.sqrt(p) * Z]
    if name == "depol":
        return [math.sqrt(1 - p) * I2] + [math.sqrt(p / 3) * P for P in (X, Y, Z)]
    if name == "ampdamp":
        return [np.array([[1, 0], [0, math.sqrt(1 - p)]], dtype=complex),
                np.array([[0, math.sqrt(p)], [0, 0]], dtype=complex)]
    raise ValueError(name)


def depol2_kraus(p):
    """Two-qubit depolarizing: (1 - p) I and p / 15 on each of the 15 other Pauli pairs. qargs [a, b]: b is the high factor."""
    P = [I2, X, Y, Z]
    return [math.sqrt(1 - p) * np.eye(4, dtype=complex)] + [math.sqrt(p / 15) * np.kron(P[m % 4], P[m // 4]) for m in range(1, 16)]


ONE_Q = ("h", "x", "y", "z", "ry")
TWO_Q = ("cx",)


def exact_rho(n, ops):
    """The density matrix after `ops` (tuples as in the .qc format, noise included)."""
    rho = DensityMatrix.from_int(0, 2 ** n)
    m1 = m2 = 0.0
    g1, g2 = {}, {}
    coh, gt = {}, {1: 0, 2: 0}

    def relax(rho, q, ns):
        # Qiskit Aer's thermal-relaxation channel, independent of src/profile.cho's formula.
        if ns > 0 and q in coh:
            rho = rho.evolve(Kraus(thermal_relaxation_error(coh[q][0], coh[q][1], ns)), qargs=[q])
        return rho

    for name, *a in ops:
        if name in ("h", "x", "y", "z"):
            rho = rho.evolve(Operator({"h": HGate, "x": XGate, "y": YGate, "z": ZGate}[name]()), qargs=[a[0]])
        elif name == "cx":
            rho = rho.evolve(Operator(CXGate()), qargs=[a[0], a[1]])
        elif name == "ry":
            rho = rho.evolve(Operator(RYGate(math.pi * a[1] / a[2])), qargs=[a[0]])
        elif name in ("bitflip", "phaseflip", "depol", "ampdamp"):
            rho = rho.evolve(Kraus(kraus(name, a[1] / a[2])), qargs=[a[0]])
        elif name == "depol2":
            rho = rho.evolve(Kraus(depol2_kraus(a[2] / a[3])), qargs=[a[0], a[1]])
        elif name in ("model1", "model2"):
            val = a[0] / a[1] if a[0] else 0.0
            if name == "model1":
                m1 = val
            else:
                m2 = val
        elif name == "gate1err":
            g1[a[0]] = a[1] / a[2] if a[1] else 0.0
        elif name == "gate2err":
            g2[frozenset((a[0], a[1]))] = a[2] / a[3] if a[2] else 0.0
        elif name == "coher":
            coh[a[0]] = (a[1], a[2])
        elif name in ("time1", "time2"):
            gt[int(name[-1])] = a[0]
        elif name == "wait":
            rho = relax(rho, a[0], a[1])
        else:
            raise ValueError(name)
        # The gate-noise model acts after each gate, never after a noise operation.
        p1 = g1[a[0]] if (name in ONE_Q and a[0] in g1) else m1
        if name in ONE_Q and p1 > 0.0:
            rho = rho.evolve(Kraus(kraus("depol", p1)), qargs=[a[0]])
        p2 = g2[frozenset((a[0], a[1]))] if (name in TWO_Q and frozenset((a[0], a[1])) in g2) else m2
        if name in TWO_Q and p2 > 0.0:
            rho = rho.evolve(Kraus(depol2_kraus(p2)), qargs=[a[0], a[1]])
        if name in ONE_Q:
            rho = relax(rho, a[0], gt[1])
        if name in TWO_Q:
            rho = relax(rho, a[0], gt[2])
            rho = relax(rho, a[1], gt[2])
    return rho.data


def one_run(exe, n, ops, seed):
    text = f"n {n}\nseed {seed}\n" + "".join(" ".join(str(x) for x in op) + "\n" for op in ops)
    out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout
    psi = np.zeros(2 ** n, dtype=complex)
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "amp":
            psi[int(f[1])] = complex(float(f[2]), float(f[3]))
    return psi


def ensemble(exe, n, ops, shots, workers=8):
    """Mean of |psi><psi| over seeds 1..shots, and the standard error of each real/imaginary part."""
    d = 2 ** n
    s1 = np.zeros((d, d), dtype=complex)
    s2 = np.zeros((d, d), dtype=complex)  # sums of squares of real and imaginary parts, kept apart
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for psi in pool.map(lambda k: one_run(exe, n, ops, k), range(1, shots + 1)):
            m = np.outer(psi, psi.conj())
            s1 += m
            s2 += m.real ** 2 + 1j * m.imag ** 2
    mean = s1 / shots
    var = (s2 / shots).real - mean.real ** 2 + 1j * ((s2 / shots).imag - mean.imag ** 2)
    se = np.sqrt(np.maximum(var.real, 0) / shots) + 1j * np.sqrt(np.maximum(var.imag, 0) / shots)
    return mean, se
