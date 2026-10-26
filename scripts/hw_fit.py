#!/usr/bin/env python3
"""Fit four scale factors of the calibration-derived noise model to what a device measured, and test the fitted model on circuits it was not fitted to.

    QSIM=path/to/qsim python3 scripts/hw_fit.py docs/data/hardware/ibm_fez-2026-10-26-mirror-from60.json \
        --fit-circuits ghzm3,rmir5_d2,rmir5_d4 [--test OTHER.json ...]

The model is `hw_model.py`'s (docs/calibration.md): after each gate the qubits decay (T1, T2 from the calibration) and are
depolarized with the probability the published gate error leaves once the decay is taken out; read-out error is the published
one. Four numbers multiply those parts: `decay` (the rate of T1/T2 decay), `depol1` and `depol2` (the depolarizing probabilities of
one- and two-qubit gates) and `readout`. All 1 is the calibration as published. The fit chooses the four that make the exact density
matrix (`qsim`'s `dm`) closest to the counts the device returned in the circuits given with `--fit-circuits`
(default: all of the file): minimum of a Pearson chi-square misfit per shot (see `nll`), Nelder-Mead on the logarithms of the factors, each
kept between 1/20 and 20.

It then compares, for every circuit not used in the fit (the rest of the file, then every circuit of each `--test` file), the
distance between the model's distribution and the device's counts (total variation, which a perfect model still shows as sampling noise,
0.01 to 0.05 at 2000 shots) with the factors all 1 and with the fitted ones. A fit that helps only the circuits it saw has learned
nothing; the held-out rows are the result.

The idea behind it: the finding of docs/hardware.md was that the calibration-based model is right on one device and wrong, in
both directions, on another. If the calibration's rates are off by a factor but the physics is right, a few numbers from circuits run
just before the real job would fix it; if not, the fit will not help the held-out circuits and the model is missing something else.
Writes `fit-<file>.json` beside the data.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_model  # noqa: E402

LIMIT = math.log(20.0)
NAMES = ("decay", "depol1", "depol2", "readout")


class Job:
    def __init__(self, path):
        self.path = path
        stem = hw_model.stem(path)
        self.doc = json.load(open(path))
        self.circuits = json.load(open(stem + "-circuits.json"))["circuits"]
        self.dev = hw_model.Device(json.load(open(stem + "-props.json")))
        self.rows = {r["circuit"]: (r, c) for r, c in zip(self.doc["circuits"], self.circuits)}
        self.cache = {}

    def names(self):
        return list(self.rows)

    def predict(self, name, x, p01=None):
        """The model's distribution over the measured bits for circuit `name` with log-scales `x`. `p01` (physical qubit -> P(read 1 | 0))
        replaces the calibration's value for those qubits."""
        s = dict(zip(NAMES, (math.exp(max(-LIMIT, min(LIMIT, v))) for v in x)))
        row, c = self.rows[name]
        text, phys, measured = hw_model.build(c["qasm3"], self.dev, s)
        res = subprocess.run([os.environ.get("QSIM", "qsim")], input=text, capture_output=True, text=True, check=True)
        probs = {l.split()[1]: float(l.split()[2]) for l in res.stdout.splitlines() if l.startswith("prob ")}
        dev = self.dev.scaled(s["readout"])
        if p01:
            dev.readout = dict(dev.readout)
            for q, v in p01.items():
                if q in dev.readout:
                    dev.readout[q] = (v, dev.readout[q][1])
        return hw_model.readout_confusion(probs, phys, measured, dev)

    def qubits(self, names):
        """The physical qubits the circuits `names` measure."""
        out = set()
        for n in names:
            _, phys, _ = hw_model.build(self.rows[n][1]["qasm3"], self.dev)
            out.update(phys)
        return sorted(out)

    def counts(self, name):
        return {k.replace(" ", ""): v for k, v in self.rows[name][0]["device"].items()}


def nll(job, names, x, p01=None):
    """The misfit per shot: Pearson's chi-square, sum over outcomes of (observed - expected)^2 / (expected + 1), divided by the shots.
    (The likelihood itself was tried first and is dominated by outcomes the model gives probability near 0 and the device
    showed once: a few such counts outweighed the bulk and the fit got worse on the very circuits it was fitted to.)"""
    total, shots = 0.0, 0
    for name in names:
        p = job.predict(name, x, p01)
        c = job.counts(name)
        n = sum(c.values())
        for k in set(p) | set(c):
            e = n * p.get(k, 0.0)
            total += (c.get(k, 0) - e) ** 2 / (e + 1.0)
        shots += n
    return total / shots


def distance(job, name, x, p01=None):
    d = hw_model.normal(job.counts(name))
    return hw_model.tvd(job.predict(name, x, p01), d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--fit-circuits", help="comma-separated names (default: all)")
    ap.add_argument("--test", nargs="*", default=[], help="other job files: every circuit of each is a test")
    ap.add_argument("--free", default="decay,depol1,depol2", help="which factors the fit may change (default: not the read-out, which a scan or the calibration gives); the rest stay 1")
    ap.add_argument("--per-qubit-readout", action="store_true", help="also fit, for each qubit the fitted circuits measure, its own P(read 1 | prepared 0) (an absolute value, kept for the other runs)")
    ap.add_argument("--tag", default="", help="added to the output file name (fit-<tag>-<file>)")
    ap.add_argument("--prior", type=float, default=math.log(3.0), help="the fit is pulled towards 1: a penalty of (log factor)^2 / (2 prior^2) in the total misfit (default log 3)")
    args = ap.parse_args()
    job = Job(args.file)
    fit_names = args.fit_circuits.split(",") if args.fit_circuits else job.names()
    held = [n for n in job.names() if n not in fit_names]
    free = [NAMES.index(n) for n in args.free.split(",") if n]
    x0 = np.zeros(4)
    shots = sum(sum(job.counts(n).values()) for n in fit_names)
    qubits = job.qubits(fit_names) if args.per_qubit_readout else []
    base = {q: max(job.dev.readout[q][0], 1e-3) for q in qubits}   # the calibration's value is where each qubit's prior sits

    def lift(z):
        x = np.zeros(4)
        x[free] = z[: len(free)]
        return x

    def p01_of(z):
        return {q: min(0.5, base[q] * math.exp(max(-LIMIT, min(LIMIT, v)))) for q, v in zip(qubits, z[len(free):])}

    def objective(z):
        # the misfit per shot, plus the prior's share of it
        return nll(job, fit_names, lift(z), p01_of(z)) + 0.5 * float(np.sum(np.square(z))) / (args.prior ** 2) / shots

    before = nll(job, fit_names, x0)
    k = len(free) + len(qubits)
    res = minimize(objective, np.zeros(k), method="Nelder-Mead",
                   options={"xatol": 0.02, "fatol": 1e-6, "maxfev": 400, "initial_simplex": np.vstack([np.zeros(k)] + [0.5 * np.eye(k)[i] for i in range(k)])})
    x = np.clip(lift(res.x), -LIMIT, LIMIT)
    fitted_p01 = p01_of(res.x)
    res.fun = nll(job, fit_names, x, fitted_p01)
    scales = {n: math.exp(v) for n, v in zip(NAMES, x)}
    print(f"{os.path.basename(args.file)}: fitted on {fit_names}")
    print("  factors: " + "  ".join(f"{n} {scales[n]:.2f}" for n in NAMES) + f"   (misfit per shot {before:.4f} -> {res.fun:.4f}, {res.nfev} runs)")
    if qubits:
        print("  P(read 1 | 0) per qubit, calibration -> fitted: " + "  ".join(f"{q}: {job.dev.readout[q][0]:.3f} -> {fitted_p01[q]:.3f}" for q in qubits))
    rows = []

    def report(label, j, names):
        for n in names:
            a, b = distance(j, n, x0), distance(j, n, x, fitted_p01)
            rows.append({"file": os.path.basename(j.path), "circuit": n, "role": label, "model_vs_device_calibration": a, "model_vs_device_fitted": b})
            print(f"  {label:9} {os.path.basename(j.path)[:48]:48} {n:9} {a:7.4f} -> {b:7.4f}")

    print(f"  {'':9} {'':48} {'circuit':9} {'calibration':>11}  fitted   (distance between the model's distribution and the device's counts)")
    report("fitted", job, fit_names)
    report("held out", job, held)
    for f in args.test:
        j = Job(f)
        report("other run", j, j.names())
    out = os.path.join(os.path.dirname(args.file), "fit-" + (args.tag + "-" if args.tag else "") + os.path.basename(args.file))
    json.dump({"free": args.free, "prior": args.prior, "fitted_on": os.path.basename(args.file), "fit_circuits": fit_names, "factors": scales, "p01_fitted": {str(q): v for q, v in fitted_p01.items()}, "p01_calibration": {str(q): job.dev.readout[q][0] for q in qubits}, "misfit_before": before, "misfit_after": res.fun,
               "evaluations": int(res.nfev), "rows": rows}, open(out, "w"), indent=1)
    print("wrote", os.path.relpath(out, hw_model.ROOT))


if __name__ == "__main__":
    main()
