#!/usr/bin/env python3
"""Bell-pair fidelity against depolarizing noise: simulated runs and the exact curve.

    CANCHO=path/to/cancho python3 scripts/noise_curve.py

Writes docs/data/noise_curve.json, which the landing page draws. For each
probability p = k/20 (k = 0..10) a Bell pair (H, CNOT) goes through a
depolarizing channel on qubit 1. The exact fidelity <Phi+|rho|Phi+> comes from
the Kraus operators (scripts/noise_lib.py); the estimate is the mean of
|<Phi+|psi>|^2 over 2000 seeded runs of `qsim`, with its standard error. The
seeds are fixed, so the file is reproducible.
"""
import json
import math
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build  # noqa: E402
from noise_lib import exact_rho, one_run  # noqa: E402
import concurrent.futures as cf  # noqa: E402

SHOTS = 2000


def main():
    exe = os.path.join(tempfile.mkdtemp(prefix="curve-"), "qsim")
    build(os.environ.get("CANCHO", "cancho"), "cranelift", exe)
    phi = np.array([1, 0, 0, 1], dtype=complex) / math.sqrt(2)
    rows = []
    for k in range(0, 11):
        ops = [("h", 0), ("cx", 0, 1), ("depol", 1, k, 20)]
        exact = float((phi.conj() @ exact_rho(2, ops) @ phi).real)
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            f = [abs(phi.conj() @ psi) ** 2 for psi in pool.map(lambda s: one_run(exe, 2, ops, s), range(1, SHOTS + 1))]
        est, se = float(np.mean(f)), float(np.std(f, ddof=1) / math.sqrt(SHOTS))
        rows.append({"p": k / 20, "exact": exact, "estimate": est, "stderr": se})
        print(f"p={k / 20:.2f}  exact {exact:.4f}  runs {est:.4f} +/- {se:.4f}")
    path = os.path.join(ROOT, "docs", "data", "noise_curve.json")
    with open(path, "w") as out:
        json.dump({"shots": SHOTS, "channel": "depolarizing on qubit 1 of a Bell pair", "rows": rows}, out, indent=2)
        out.write("\n")


if __name__ == "__main__":
    main()
