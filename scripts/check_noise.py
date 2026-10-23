#!/usr/bin/env python3
"""Noise against an exact density-matrix calculation.

    CANCHO=path/to/cancho python3 scripts/check_noise.py [--shots 4000] [--exe qsim]

A noisy circuit run once gives one pure state, a sample of what a noisy machine
did. The claim to test is that the *average* over many runs is the density
matrix the channels define. For each circuit below this script computes that
matrix exactly (Kraus operators, `scripts/noise_lib.py`), runs `qsim` with seeds
1..N, averages |psi><psi|, and requires every real and imaginary part of every
entry to be within 4.5 of its own standard errors. An entry whose runs never
varied must match to 1e-12. It prints the largest z-score and the trace distance
in each case.
"""
import argparse
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import build  # noqa: E402
from noise_lib import ensemble, exact_rho  # noqa: E402

CIRCUITS = {
    "depolarized Bell pair": (2, [("h", 0), ("cx", 0, 1), ("depol", 1, 1, 4)]),
    "bit and phase flips on a rotated qubit": (2, [("ry", 0, 1, 3), ("bitflip", 0, 1, 5), ("phaseflip", 0, 1, 3), ("cx", 0, 1), ("bitflip", 1, 1, 4)]),
    "amplitude damping of |+> and a Bell pair": (2, [("h", 0), ("ampdamp", 0, 1, 3), ("cx", 0, 1), ("ampdamp", 1, 1, 2)]),
    "all four channels on 3 qubits": (3, [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("depol", 0, 1, 6), ("ampdamp", 1, 1, 4),
                                          ("phaseflip", 2, 1, 5), ("bitflip", 1, 1, 7), ("ry", 2, 1, 4), ("depol", 2, 1, 3)]),
}


def trace_distance(a, b):
    return 0.5 * float(np.sum(np.abs(np.linalg.eigvalsh(a - b))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=int, default=4000)
    ap.add_argument("--exe")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    exe = args.exe or os.path.join(tempfile.mkdtemp(prefix="noise-"), "qsim")
    if not args.exe:
        build(args.compiler, "cranelift", exe)
    failed, results = [], []
    for name, (n, ops) in CIRCUITS.items():
        want = exact_rho(n, ops)
        got, se = ensemble(exe, n, ops, args.shots)
        diff = got - want
        worst, bad = 0.0, False
        for part, d, s in ((0, diff.real, se.real), (1, diff.imag, se.imag)):
            for idx in np.ndindex(d.shape):
                if s[idx] < 1e-12:
                    if abs(d[idx]) > 1e-12:
                        bad = True
                else:
                    worst = max(worst, abs(d[idx]) / s[idx])
        bad = bad or worst > 4.5
        td = trace_distance(got, want)
        print(("FAIL " if bad else "ok   ") + f"{name:44s} max z {worst:4.2f}  trace distance {td:.4f}  ({args.shots} runs)")
        results.append({"circuit": name, "max_z": round(worst, 2), "trace_distance": round(td, 4)})
        if bad:
            failed.append(name)
    # The test must be able to fail: a wrong channel (twice the probability) is caught.
    n, ops = CIRCUITS["depolarized Bell pair"]
    wrong = [(o[0], o[1], 2 * o[2], o[3]) if o[0] == "depol" else o for o in ops]
    got, se = ensemble(exe, n, wrong, args.shots)
    diff = got - exact_rho(n, ops)
    z = max(np.max(np.abs(diff.real) / np.maximum(se.real, 1e-12)), np.max(np.abs(diff.imag) / np.maximum(se.imag, 1e-12)))
    caught = z > 4.5
    print(("ok   " if caught else "FAIL ") + f"a deliberately wrong probability is caught (max z {z:.1f})")
    if not caught:
        failed.append("sensitivity")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "data", "noise_check.json")
    with open(out, "w") as f:
        json.dump({"shots": args.shots, "circuits": results, "wrong_probability_z": round(float(z), 1)}, f, indent=2)
        f.write("\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
