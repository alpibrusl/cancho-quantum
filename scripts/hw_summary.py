#!/usr/bin/env python3
"""The numbers of docs/hardware.md that the landing page quotes, computed from the files under docs/data/hardware/.

    python3 scripts/hw_summary.py [--check]

Writes docs/data/hardware_summary.json (`--check`: fails if it is not what the files give). Only the runs that docs/hardware.md
counts as measurements of the model are used: the mirror circuits on a line of qubits from 60 on `ibm_kingston` (the healthy
device) and every mirror run on `ibm_fez`. The first kingston run (qubit 0 stuck at 1) is evidence of the fault, not of the model.

  healthy_*  the device the model matched: the worst gap between the device's and `qsim`'s total-variation distance from the
             ideal output, over all its runs and circuits, and the most `cz` gates in one circuit
  drift_*    the device it did not match: the same gap, and the range of device / `qsim` distance
  stuck_*    the qubit that read 1 when idle: how often, from the idle measurement
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HW = os.path.join(ROOT, "docs", "data", "hardware")
OUT = os.path.join(ROOT, "docs", "data", "hardware_summary.json")
DAY = "2026-10-26"
TAGS = {"ibm_kingston": ["mirror-from60", "mirror-from60-1000", "mirror-from60-1030"],
        "ibm_fez": ["mirror", "mirror-from60", "mirror-from60-1000", "mirror-from60-1030"]}


def rows(device):
    for tag in TAGS[device]:
        doc = json.load(open(os.path.join(HW, f"{device}-{DAY}-{tag}-qsim.json")))
        for r in doc["rows"]:
            yield r


def summary():
    healthy = list(rows("ibm_kingston"))
    drift = list(rows("ibm_fez"))
    job = json.load(open(os.path.join(HW, f"ibm_kingston-{DAY}-mirror-from60.json")))
    idle = json.load(open(os.path.join(HW, f"ibm_kingston-{DAY}-diagnostic.json")))["runs"][0]["counts"]
    stuck = sum(v for k, v in idle.items() if k[-1] == "1") / sum(idle.values())   # bit 0 is the rightmost
    ratios = [r["tvd_device"] / r["tvd_qsim"] for r in drift]
    return {
        "date": DAY,
        "shots": job["shots"],
        "healthy_device": "ibm_kingston",
        "healthy_runs": len(healthy),
        "healthy_max_cz": max(c["transpiled"]["two_qubit_gates"] for c in job["circuits"]),
        "healthy_worst_gap": max(abs(r["tvd_device"] - r["tvd_qsim"]) for r in healthy),
        "drift_device": "ibm_fez",
        "drift_runs": len(drift),
        "drift_worst_gap": max(abs(r["tvd_device"] - r["tvd_qsim"]) for r in drift),
        "drift_ratio_min": min(ratios),
        "drift_ratio_max": max(ratios),
        "stuck_qubit": 0,
        "stuck_percent": 100.0 * stuck,
    }


def main():
    text = json.dumps(summary(), indent=1) + "\n"
    if "--check" in sys.argv:
        if not os.path.exists(OUT) or open(OUT).read() != text:
            sys.exit("docs/data/hardware_summary.json is out of date: run scripts/hw_summary.py")
        print("docs/data/hardware_summary.json is up to date")
    else:
        open(OUT, "w").write(text)
        print(text, end="")


if __name__ == "__main__":
    main()
