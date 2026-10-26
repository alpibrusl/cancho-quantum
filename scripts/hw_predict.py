#!/usr/bin/env python3
"""Does a calibration made just before a run predict the run? The published calibration, a read-out scan, and gate rates fitted by regression, each on its own and together, against the counts.

    QSIM=... STATS=... python3 scripts/hw_predict.py JOB.json [--scan SCAN.json] [--rates RATES.json]

`JOB.json` is a `hw_spike.py run` file whose circuits and calibration `hw_model.py fetch` has saved. `SCAN.json` is a `hw_spike.py check` file
(read-out errors measured just before) and `RATES.json` the `-rates.json` that `hw_rates.py` wrote (gate errors fitted from a `--set rates` run on the same qubits). For each circuit of the job
the exact density-matrix model (`hw_model.py`'s, docs/calibration.md) is run with:

  calibration        everything as published
  + scan             the read-out errors of the scan for the qubits it measured
  + rates            each gate's published error replaced by its fitted lambda (the loss of fidelity per gate; `sx` and `x` of a qubit share one, `cz` of a pair has its own)
  + scan + rates     both

and the distance from the device's counts (total variation) and the chi-square goodness-of-fit p-value (`stats test chisq`, as `hw_gof.py`) are printed for each. The
decay (T1, T2) stays the published one: the question is whether what can be measured in minutes, the read-out and the gate errors, is enough to turn a model that the counts reject into one they do not.
A variant for which the counts are not rejected (p above 0.05) on most circuits is a model of that run; if none is, something other than read-out and gate error is missing.
The rates are applied only to gates on qubits the regression measured; any other gate keeps its published error. Nothing is fitted to the job's own counts.
"""
import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_gof  # noqa: E402
import hw_model  # noqa: E402


def variant(job_dev, scan, rates):
    """A copy of the device with the scan's read-out and the fitted gate errors."""
    import copy

    dev = copy.copy(job_dev)
    dev.readout = dict(dev.readout)
    dev.gates = dict(dev.gates)
    if scan:
        for q, v in scan["qubits"].items():
            if int(q) in dev.readout:
                dev.readout[int(q)] = (v["idle_reads_1"], v["after_x_reads_0"])
    if rates:
        lam = rates["lambda_fitted"]
        for (name, qs), (r, ns) in list(dev.gates.items()):
            if name in ("sx", "x") and f"g1_{qs[0]}" in lam:
                dev.gates[(name, qs)] = (lam[f"g1_{qs[0]}"], ns)
            elif name == "cz":
                key = f"cz_{qs[0]}_{qs[1]}" if f"cz_{qs[0]}_{qs[1]}" in lam else f"cz_{qs[1]}_{qs[0]}"
                if key in lam:
                    dev.gates[(name, qs)] = (lam[key], ns)
    return dev


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job")
    ap.add_argument("--scan")
    ap.add_argument("--rates")
    args = ap.parse_args()
    qsim = os.environ.get("QSIM", "qsim")
    stem = hw_model.stem(args.job)
    doc = json.load(open(args.job))
    circuits = json.load(open(stem + "-circuits.json"))["circuits"]
    dev = hw_model.Device(json.load(open(stem + "-props.json")))
    scan = json.load(open(args.scan)) if args.scan else None
    rates = json.load(open(args.rates)) if args.rates else None
    variants = [("calibration", variant(dev, None, None))]
    if scan:
        variants.append(("+ scan", variant(dev, scan, None)))
    if rates:
        variants.append(("+ rates", variant(dev, None, rates)))
    if scan and rates:
        variants.append(("+ scan + rates", variant(dev, scan, rates)))
    print(f"{doc['device']}  job {doc['date']}  {doc['shots']} shots" + (f"  scan {scan['date']}" if scan else "") + (f"  rates {rates['job']}" if rates else ""))
    print(f"{'circuit':9} " + " ".join(f"{name:>22}" for name, _ in variants) + "      (total variation, p-value)")
    table = {name: [] for name, _ in variants}
    for row, c in zip(doc["circuits"], circuits["circuits"] if isinstance(circuits, dict) else circuits):
        counts = {k.replace(" ", ""): v for k, v in row["device"].items()}
        cells = []
        for name, d in variants:
            text, phys, measured = hw_model.build(c["qasm3"], d)
            res = subprocess.run([qsim], input=text, capture_output=True, text=True, check=True)
            probs = {l.split()[1]: float(l.split()[2]) for l in res.stdout.splitlines() if l.startswith("prob ")}
            model = hw_model.readout_confusion(probs, phys, measured, d)
            tv = hw_model.tvd(model, hw_model.normal(counts))
            p = float(hw_gof.test(counts, model)["p_value"])
            table[name].append({"circuit": row["circuit"], "tvd": tv, "p_value": p})
            cells.append(f"{tv:8.4f} {p:12.2g}")
        print(f"{row['circuit']:9} " + " ".join(f"{x:>22}" for x in cells))
    print()
    summary = {}
    for name, _ in variants:
        rs = table[name]
        summary[name] = {"mean_tvd": sum(r["tvd"] for r in rs) / len(rs), "p_above_0.05": sum(r["p_value"] > 0.05 for r in rs), "circuits": len(rs)}
        print(f"  {name:16} mean distance {summary[name]['mean_tvd']:.4f}   not rejected (p > 0.05): {summary[name]['p_above_0.05']} of {len(rs)}")
    out = stem + "-predict.json"
    json.dump({"job": os.path.basename(args.job), "scan": os.path.basename(args.scan) if args.scan else None, "rates": os.path.basename(args.rates) if args.rates else None,
               "summary": summary, "rows": table}, open(out, "w"), indent=1)
    print("wrote", os.path.relpath(out, hw_model.ROOT))


if __name__ == "__main__":
    main()
