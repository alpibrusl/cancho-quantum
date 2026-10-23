#!/usr/bin/env python3
"""Purity of a Bell pair against depolarizing noise, exactly: cancho, Qiskit, and the formula.

    CANCHO=path/to/cancho python3 scripts/purity_curve.py

Writes docs/data/purity_curve.json for the landing page. For p = k/20 a Bell
pair goes through a depolarizing channel on one qubit, in `qsim`'s density-matrix
mode (`dm 2`, then `purity`). The same circuit is evolved by Qiskit's
DensityMatrix with Kraus operators from `scripts/noise_lib.py`; the formula is
(1 - p)^2 + p^2 / 3, from rho = (1 - p)|Phi+><Phi+| + (p/3)(the other three Bell states).
"""
import json
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_diff import ROOT, build  # noqa: E402
from noise_lib import exact_rho  # noqa: E402

import numpy as np  # noqa: E402


def main():
    exe = os.path.join(tempfile.mkdtemp(prefix="purity-"), "qsim")
    build(os.environ.get("CANCHO", "cancho"), "cranelift", exe)
    rows = []
    for k in range(0, 11):
        ops = [("h", 0), ("cx", 0, 1), ("depol", 1, k, 20)]
        text = "dm 2\n" + "".join(" ".join(str(x) for x in op) + "\n" for op in ops) + "purity\nquiet\n"
        out = subprocess.run([exe], input=text, capture_output=True, text=True, check=True).stdout
        ours = float(out.split()[1])
        rho = exact_rho(2, ops)
        theirs = float(np.real(np.trace(rho @ rho)))
        p = k / 20
        rows.append({"p": p, "exact": (1 - p) ** 2 + p ** 2 / 3, "estimate": ours, "stderr": 0.0, "qiskit": theirs})
        print(f"p={p:.2f}  cancho {ours:.15f}  qiskit {theirs:.15f}  formula {(1 - p) ** 2 + p ** 2 / 3:.15f}")
    worst = max(max(abs(r["estimate"] - r["qiskit"]), abs(r["estimate"] - r["exact"])) for r in rows)
    with open(os.path.join(ROOT, "docs", "data", "purity_curve.json"), "w") as f:
        json.dump({"channel": "depolarizing on one qubit of a Bell pair", "worst_difference": worst, "rows": rows}, f, indent=2)
        f.write("\n")
    print(f"worst difference between cancho, Qiskit and the formula: {worst:.2e}")


if __name__ == "__main__":
    main()
