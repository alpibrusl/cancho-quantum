#!/usr/bin/env python3
"""Check the real-calibration profile: where every number came from, and what it does to a circuit.

    CANCHO=path/to/cancho python3 scripts/check_calibration.py [--exe qsim]

`profiles/ibm_perth_2024-05-27.json` is made by `scripts/calibration_import.py` from the
calibration `ibm_perth` published on 2024-05-27 (as shipped in qiskit-ibm-runtime). Two checks:

1. Provenance. Every readout error, T1, T2 and gate time in the profile is re-read from the raw
   snapshot, and every depolarizing rate is recomputed with Qiskit Aer's own thermal-relaxation
   channel and Qiskit's `average_gate_fidelity`, a different route from the importer's NumPy one.
2. Behaviour. Two circuits of native gates (`x`, `sx` as `rx 1/2`, `cx`) run on the density matrix
   (`dm 7`) through the profile, and in Qiskit Aer with `NoiseModel.from_backend` on the same
   snapshot. The two final states are compared by trace distance, against the distance of
   either from the ideal state. Two controls must be far worse: no idle noise at all, and the
   published gate errors used as depolarizing rates without taking the decay out.

Writes docs/data/calibration_check.json for the landing page.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noise_profile  # noqa: E402
from calibration_import import prop, snapshot  # noqa: E402
from check_diff import ROOT, build  # noqa: E402

from qiskit import QuantumCircuit, transpile  # noqa: E402
from qiskit.quantum_info import DensityMatrix, Kraus, average_gate_fidelity  # noqa: E402
from qiskit_aer import AerSimulator  # noqa: E402
from qiskit_aer.noise import NoiseModel, thermal_relaxation_error  # noqa: E402
from qiskit_ibm_runtime.fake_provider import FakePerth  # noqa: E402

PROFILE = os.path.join(ROOT, "profiles", "ibm_perth_2024-05-27.json")
CIRCUITS = {
    "a chain of 13 native gates": [("sx", 1), ("sx", 3), ("cx", 1, 3), ("x", 0), ("sx", 0), ("cx", 0, 1), ("sx", 5), ("cx", 3, 5),
                                   ("cx", 5, 6), ("x", 4), ("cx", 4, 5), ("sx", 2), ("cx", 1, 2)],
    "GHZ-like, then undone": [("sx", 3), ("cx", 3, 1), ("cx", 3, 5), ("cx", 1, 0), ("cx", 5, 6), ("cx", 5, 6), ("cx", 1, 0), ("cx", 3, 5),
                              ("cx", 3, 1), ("sx", 3), ("sx", 3)],
}


def trace_distance(a, b):
    return 0.5 * float(np.sum(np.abs(np.linalg.eigvalsh(a - b))))


def provenance(raw, prof):
    """Re-derive every number from the raw snapshot. Returns (checked, worst difference)."""
    checked, worst = 0, 0.0   # worst: over the probabilities and rates (nanoseconds are rounded to whole ones, within 0.5)

    def near(a, b, tol=1e-12):
        nonlocal checked, worst
        checked += 1
        if tol < 0.1:
            worst = max(worst, abs(a - b))
        if abs(a - b) > tol:
            sys.exit(f"provenance: {a!r} != {b!r}")

    coh = {}
    for q, items in enumerate(raw["qubits"]):
        t1, t2 = prop(items, "T1") * 1000.0, prop(items, "T2") * 1000.0
        t2 = min(t2, 2 * t1)
        near(prof["coherence"]["per_qubit"][str(q)][0], t1, 0.5)
        near(prof["coherence"]["per_qubit"][str(q)][1], t2, 0.5)
        coh[q] = tuple(prof["coherence"]["per_qubit"][str(q)])
        near(prof["readout"]["per_qubit"][str(q)][0], prop(items, "prob_meas1_prep0"))
        near(prof["readout"]["per_qubit"][str(q)][1], prop(items, "prob_meas0_prep1"))
        sx = next(g for g in raw["gates"] if g["gate"] == "sx" and g["qubits"] == [q])
        r, ln = prop(sx["parameters"], "gate_error"), prop(sx["parameters"], "gate_length")
        near(prof["gate1"]["time_ns"]["per_qubit"][str(q)], ln, 0.5)
        relax = 1.0 - average_gate_fidelity(Kraus(thermal_relaxation_error(*coh[q], ln)))
        near(prof["gate1"]["per_qubit"][str(q)], 1.5 * max(0.0, r - relax), 1e-9)
    for key, p in prof["gate2"]["per_pair"].items():
        a, b = map(int, key.split("-"))
        cx = [g for g in raw["gates"] if g["gate"] == "cx" and g["qubits"] in ([a, b], [b, a])]
        r = sum(prop(g["parameters"], "gate_error") for g in cx) / len(cx)
        ln = sum(prop(g["parameters"], "gate_length") for g in cx) / len(cx)
        near(prof["gate2"]["time_ns"]["per_pair"][key], ln, 0.5)
        relax = 1.0 - average_gate_fidelity(Kraus(thermal_relaxation_error(*coh[a], ln)).tensor(Kraus(thermal_relaxation_error(*coh[b], ln))))
        near(p, 1.25 * max(0.0, r - relax), 1e-9)
    return checked, worst


def run_dm(exe, text):
    out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout
    rho = np.zeros((128, 128), dtype=complex)
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "rho":
            rho[int(f[1]), int(f[2])] = complex(float(f[3]), float(f[4]))
    return rho


def circuit_text(ops):
    lines = ["dm 7"]
    for o in ops:
        lines.append(f"cx {o[1]} {o[2]}" if o[0] == "cx" else (f"x {o[1]}" if o[0] == "x" else f"rx {o[1]} 1 2"))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    exe = args.exe or os.path.join(tempfile.mkdtemp(prefix="calib-"), "qsim")
    if not args.exe:
        build(args.compiler, "cranelift", exe)
    prof = json.load(open(PROFILE))
    raw = json.load(open(snapshot("perth")))
    checked, worst = provenance(raw, prof)
    print(f"ok   provenance: {checked} numbers re-derived from the raw snapshot, worst difference of a rate {worst:.1e}; times to the nanosecond")

    # The controls: the same profile without the idle decay, and with the published error used as is.
    no_idle = {k: v for k, v in prof.items() if k != "coherence"}
    no_idle["gate1"] = {"per_qubit": prof["gate1"]["per_qubit"]}
    no_idle["gate2"] = {"per_pair": prof["gate2"]["per_pair"]}
    naive = json.loads(json.dumps(no_idle))
    for g in raw["gates"]:
        if g["gate"] == "sx":
            naive["gate1"]["per_qubit"][str(g["qubits"][0])] = 1.5 * prop(g["parameters"], "gate_error")
    for key in naive["gate2"]["per_pair"]:
        a, b = map(int, key.split("-"))
        cx = [g for g in raw["gates"] if g["gate"] == "cx" and g["qubits"] in ([a, b], [b, a])]
        naive["gate2"]["per_pair"][key] = 1.25 * sum(prop(g["parameters"], "gate_error") for g in cx) / len(cx)

    nm = NoiseModel.from_backend(FakePerth(), thermal_relaxation=True, gate_error=True, readout_error=False)
    sim = AerSimulator(method="density_matrix", noise_model=nm)
    results, failed = [], False
    for name, ops in CIRCUITS.items():
        qc, ideal = QuantumCircuit(7), QuantumCircuit(7)
        for o in ops:
            getattr(qc, o[0])(*o[1:])
            getattr(ideal, o[0])(*o[1:])
        qc.save_density_matrix()
        aer = np.array(sim.run(transpile(qc, sim, optimization_level=0)).result().data(0)["density_matrix"])
        want = DensityMatrix(ideal).data
        text = circuit_text(ops)
        ours = run_dm(exe, noise_profile.apply(prof, text))
        d_ours, d_noise = trace_distance(ours, aer), trace_distance(aer, want)
        d_no_idle = trace_distance(run_dm(exe, noise_profile.apply(no_idle, text)), aer)
        d_naive = trace_distance(run_dm(exe, noise_profile.apply(naive, text)), aer)
        ok = d_ours < 0.005 and d_ours < 0.05 * d_noise and d_no_idle > 3 * d_ours and d_naive > 3 * d_ours
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}: cancho vs Aer {d_ours:.2e}; noise itself {d_noise:.3f}; "
              f"without idle decay {d_no_idle:.2e}; published error used as is {d_naive:.2e}")
        results.append({"circuit": name, "gates": len(ops), "cancho_vs_aer": d_ours, "noise_vs_ideal": d_noise,
                        "control_no_idle": d_no_idle, "control_naive": d_naive})
    # A profile that breaks the physical limit is refused, with a message.
    bad = json.loads(json.dumps(prof))
    bad["coherence"]["per_qubit"]["0"] = [1000, 2500]
    try:
        noise_profile.operations(bad)
        print("FAIL T2 > 2 T1 was accepted")
        failed = True
    except ValueError as e:
        print(f"ok   T2 above 2 T1 is refused: {e}")
    with open(os.path.join(ROOT, "docs", "data", "calibration_check.json"), "w") as f:
        json.dump({"backend": raw["backend_name"], "snapshot": raw["last_update_date"], "numbers_rederived": checked,
                   "provenance_worst": worst, "circuits": results}, f, indent=2)
        f.write("\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
