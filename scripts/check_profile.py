#!/usr/bin/env python3
"""The noise-profile converter and what `qsim` does with its output.

    CANCHO=path/to/cancho python3 scripts/check_profile.py [--exe qsim]

1. `tools/qprofile.cho` turns profiles/example_5q.json and tests/profile/ghz5.qc into the checked-in
   tests/profile/ghz5_example_5q.qc, byte for byte.
2. `qsim` runs that circuit on the density matrix, and its probabilities and purity match a
   calculation made *from the JSON file directly* with Qiskit (it never reads the converter's
   output): per-qubit and per-pair depolarizing after each gate.
3. Profiles that are wrong are refused with a message and a non-zero exit: a probability above 1,
   a qubit outside the device, a pair of one qubit, a circuit bigger than the profile.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
from qiskit.circuit.library import CXGate, HGate
from qiskit.quantum_info import DensityMatrix, Kraus, Operator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build, parse  # noqa: E402
from noise_lib import depol2_kraus, kraus  # noqa: E402
import tools_lib  # noqa: E402


def micro(p):
    return round(p * tools_lib.DEN) / tools_lib.DEN


def independent(profile, n):
    """GHZ(n) with depolarizing noise after each gate, from the profile's own numbers."""
    g1, g2 = profile["gate1"], profile["gate2"]
    p1 = lambda q: micro(g1.get("per_qubit", {}).get(str(q), g1["default"]))
    p2 = lambda a, b: micro(g2.get("per_pair", {}).get(f"{min(a, b)}-{max(a, b)}", g2["default"]))
    rho = DensityMatrix.from_int(0, 2**n)
    rho = rho.evolve(Operator(HGate()), qargs=[0]).evolve(Kraus(kraus("depol", p1(0))), qargs=[0])
    for i in range(n - 1):
        rho = rho.evolve(Operator(CXGate()), qargs=[i, i + 1]).evolve(Kraus(depol2_kraus(p2(i, i + 1))), qargs=[i, i + 1])
    return rho.data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    exe = args.exe or os.path.join(tempfile.mkdtemp(prefix="profile-"), "qsim")
    if not args.exe:
        build(args.compiler, "cranelift", exe)
    failed = []

    def report(ok, text):
        print(("ok   " if ok else "FAIL ") + text)
        if not ok:
            failed.append(text)

    prof_path = os.path.join(ROOT, "profiles", "example_5q.json")
    profile = json.load(open(prof_path))
    circuit = open(os.path.join(ROOT, "tests", "profile", "ghz5.qc")).read()
    made = tools_lib.apply(profile, circuit)
    want = open(os.path.join(ROOT, "tests", "profile", "ghz5_example_5q.qc")).read()
    report(made == want, "the converter's output equals tests/profile/ghz5_example_5q.qc")

    out = subprocess.run([exe], input=made, capture_output=True, text=True).stdout
    got = parse(out)
    rho = independent(profile, 5)
    worst = 0.0
    probs = {bits: v for kind, *rest in got[5] if kind == "prob" for bits, v in [rest]}
    for i in range(32):
        worst = max(worst, abs(probs.get(f"{i:05b}", 0.0) - float(rho[i, i].real)))
    purity = [v for kind, *rest in got[5] if kind == "purity" for v in rest][0]
    worst = max(worst, abs(purity - float(np.trace(rho @ rho).real)))
    report(worst < 1e-12, f"qsim's density matrix matches Qiskit built from the JSON (worst difference {worst:.1e}, purity {purity:.6f})")

    def refused(mutate, circuit_text=circuit):
        bad = json.loads(json.dumps(profile))
        mutate(bad)
        try:
            tools_lib.apply(bad, circuit_text)
        except (ValueError, KeyError):
            return True
        return False

    report(refused(lambda p: p["gate1"].update(default=1.5)), "a probability above 1 is refused")
    report(refused(lambda p: p["gate1"]["per_qubit"].update({"9": 0.1})), "a qubit outside the device is refused")
    report(refused(lambda p: p["gate2"]["per_pair"].update({"2-2": 0.1})), "a pair of one qubit is refused")
    report(refused(lambda p: p["readout"]["per_qubit"].update({"1": [0.1]})), "a readout entry that is not a pair is refused")
    report(refused(lambda p: None, "n 6\nh 0\n"), "a circuit larger than the profile is refused")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
