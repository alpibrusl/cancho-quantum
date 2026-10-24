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
    "two-qubit depolarizing on a Bell pair and a chain": (3, [("h", 0), ("cx", 0, 1), ("depol2", 0, 1, 1, 4), ("cx", 1, 2), ("depol2", 1, 2, 1, 3)]),
    "a gate-noise model on a GHZ state": (3, [("model1", 1, 12), ("model2", 1, 8), ("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("ry", 2, 1, 3)]),
    "per-qubit and per-pair rates (an invented profile)": (3, [("model1", 1, 100), ("gate1err", 0, 1, 15), ("gate1err", 2, 1, 6), ("model2", 1, 20),
                                                                ("gate2err", 0, 1, 1, 7), ("gate2err", 2, 1, 1, 9), ("h", 0), ("cx", 0, 1),
                                                                ("cx", 1, 2), ("ry", 2, 1, 3), ("cx", 2, 0)]),
    "all four channels on 3 qubits": (3, [("h", 0), ("cx", 0, 1), ("cx", 1, 2), ("depol", 0, 1, 6), ("ampdamp", 1, 1, 4),
                                          ("phaseflip", 2, 1, 5), ("bitflip", 1, 1, 7), ("ry", 2, 1, 4), ("depol", 2, 1, 3)]),
    "idle noise: T1/T2 on a GHZ state, gate times and a wait": (3, [("coher", 0, 50000, 70000), ("coher", 1, 30000, 20000), ("coher", 2, 40000, 80000),
                                                                 ("time1", 3500), ("time2", 30000), ("dur2", 1, 2, 9000), ("dur1", 0, 800), ("h", 0), ("cx", 0, 1), ("cx", 1, 2),
                                                                 ("wait", 0, 15000), ("ry", 2, 1, 3), ("wait", 2, 9000), ("cx", 2, 0)]),
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
    # Readout error is classical: it flips the reported bit, not the state. Each reported
    # bit is a coin, so the counts are binomial and a z-score says how far off they are.
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def run(text):
        return subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout

    def reported(seed):
        out = run(f"n 2\nseed {seed}\nx 0\nreadout 1 4\nm 0\nm 1\nquiet\n")
        return [int(l.split()[2]) for l in out.splitlines() if l.startswith("m ")]

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(reported, range(1, args.shots + 1)))
    ones0 = sum(r[0] for r in rows)       # true 1, flipped to 0 with probability 1/4
    ones1 = sum(r[1] for r in rows)       # true 0, flipped to 1 with probability 1/4
    sd = (args.shots * 0.75 * 0.25) ** 0.5
    z_ro = max(abs(ones0 - 0.75 * args.shots), abs(ones1 - 0.25 * args.shots)) / sd
    # Asymmetric readout: a true 1 on qubit 0 reads 0 one time in 10; a true 0 on qubit 1 reads 1 one time in 5.
    def asym(seed):
        out = run(f"n 2\nseed {seed}\nx 0\nreaderr 0 1 5 1 10\nreaderr 1 1 5 1 10\nm 0\nm 1\nquiet\n")
        return [int(l.split()[2]) for l in out.splitlines() if l.startswith("m ")]

    with ThreadPoolExecutor(max_workers=8) as pool:
        arows = list(pool.map(asym, range(1, args.shots + 1)))
    a0 = sum(r[0] for r in arows)         # expect 0.9 * shots
    a1 = sum(r[1] for r in arows)         # expect 0.2 * shots
    z_asym = max(abs(a0 - 0.9 * args.shots) / (args.shots * 0.9 * 0.1) ** 0.5, abs(a1 - 0.2 * args.shots) / (args.shots * 0.2 * 0.8) ** 0.5)
    ok_asym = z_asym < 4.5
    print(("ok   " if ok_asym else "FAIL ") + f"asymmetric readout (1/5 up, 1/10 down): z {z_asym:.2f}")
    if not ok_asym:
        failed.append("asymmetric readout")
    out = run("n 1\nseed 5\nx 0\nreadout 1 4\nsample 4000\nquiet\n")
    hits = sum(int(l.split()[2]) for l in out.splitlines() if l.startswith("sample 1 "))
    z_sample = abs(hits - 3000) / (4000 * 0.75 * 0.25) ** 0.5
    ok_ro = max(z_ro, z_sample) < 4.5
    print(("ok   " if ok_ro else "FAIL ") + f"readout error 1/4: measured bits z {z_ro:.2f}, 4000 samples z {z_sample:.2f}")
    if not ok_ro:
        failed.append("readout")
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
        json.dump({"shots": args.shots, "circuits": results, "wrong_probability_z": round(float(z), 1),
                   "readout": {"measured_z": round(float(z_ro), 2), "sample_z": round(float(z_sample), 2),
                               "asymmetric_z": round(float(z_asym), 2)}}, f, indent=2)
        f.write("\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
