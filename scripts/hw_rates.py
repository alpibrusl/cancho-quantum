#!/usr/bin/env python3
"""Gate error rates from a run of `hw_spike.py run --set rates`, by regression (cancho-ml's `ml fit --model linear`), and whether they predict circuits left out better than the published calibration.

    ML=path/to/ml python3 scripts/hw_rates.py docs/data/hardware/<device>-<time>-rates-from60.json

Needs the calibration beside the job file as `<job>-props.json` (`hw_model.py fetch <job>` writes it for a real run; a `--fake` run has it already).

What it does (docs/rates-regression.md): the survival S of each circuit (the share of shots that read all zeros) is, to first order, a product over its gates, so
`log S` is linear in the gate counts. Four of every five circuits (by index) are the training set: `ml fit --model linear --l2 0.001` on a CSV of their `sx`/`x` count per qubit
and `cz` count per pair against `log S` gives the rates, and a rate `lambda` is the loss of fidelity per gate (so the depolarizing probability is 1.5 lambda for a one-qubit gate
and 1.25 lambda for a two-qubit one). The fifth of the circuits left out is predicted by `ml predict` with the fitted model, and compared with the prediction
of the published calibration, whose `lambda` is the published gate error and whose intercept is the read-out (the product of the qubits' `prob_meas1_prep0` complements),
and with the training mean as a baseline. The measure is the root mean square error of `log S`, and of `S`, on the held-out circuits.

A fit that does not beat the calibration on the held-out circuits has not learned anything the calibration did not say. The conversion is first order and the model class (independent
gate errors) is the question, not a given: read the residuals as well as the rates.
"""
import csv
import json
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_model  # noqa: E402

ML = os.environ.get("ML", "ml")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    doc = json.load(open(path))
    dev = hw_model.Device(json.load(open(hw_model.stem(path) + "-props.json")))
    line, shots = doc["line"], doc["shots"]
    n = len(line)
    one = [f"g1_{q}" for q in line]
    two = [f"cz_{a}_{b}" for a, b in zip(line, line[1:])]
    cols = two + one
    rows = []
    for r in doc["circuits"]:
        zeros = r["device"].get("0" * n, 0)
        g = r["gates"]
        feats = [g["cz"].get(f"{min(a, b)}-{max(a, b)}", 0) for a, b in zip(line, line[1:])] + [g["sx_x"].get(str(q), 0) for q in line]
        rows.append((feats, math.log(max(zeros, 0.5) / shots), max(zeros, 0.5) / shots))
    train = [x for i, x in enumerate(rows) if i % 5 != 0]
    test = [x for i, x in enumerate(rows) if i % 5 == 0]
    d = tempfile.mkdtemp(prefix="rates-")

    def write(name, data, target):
        p = os.path.join(d, name)
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols + (["logS"] if target else []))
            for feats, ls, _ in data:
                w.writerow(feats + ([f"{ls:.17g}"] if target else []))
        return p

    trainp, testp = write("train.csv", train, True), write("test.csv", test, False)
    model = os.path.join(d, "rates.ml")
    r = subprocess.run([ML, "fit", "--model", "linear", "--l2", "0.001", "--target", "logS", "--output", model, trainp], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ml fit failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    summary = json.loads(r.stdout)["data"]["summary"]
    coef = {c["name"]: float(c["value"]) for c in summary["coefficients"]}
    intercept = float(summary["intercept"])
    r = subprocess.run([ML, "predict", "--model-file", model, testp], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ml predict failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    fitted = [float(x[0]) for x in json.loads(r.stdout)["data"]["rows"]]

    def published(a, b=None):
        key = ("cz", (a, b)) if b is not None else ("sx", (a,))
        return (dev.gates.get(key) or dev.gates.get(("cz", (b, a))))[0]

    lam_cal = {f"cz_{a}_{b}": published(a, b) for a, b in zip(line, line[1:])}
    lam_cal.update({f"g1_{q}": published(q) for q in line})
    readout = sum(math.log(1 - dev.readout[q][0]) for q in line)
    calib = [readout + sum(x * math.log(1 - lam_cal[c]) for x, c in zip(feats, cols)) for feats, _, _ in test]
    base = sum(ls for _, ls, _ in train) / len(train)

    def rmse(pred, what):
        return math.sqrt(sum((p - (ls if what == "logS" else s)) ** 2 for p, (_, ls, s) in zip(pred, test)) / len(test))

    print(f"{doc['device']}  {doc['date']}  {len(rows)} circuits ({len(train)} to fit, {len(test)} left out), {shots} shots, line {line}")
    print(f"intercept {intercept:.4f} (read-out from the calibration: {readout:.4f})")
    print(f"{'gate':14} {'fitted lambda':>14} {'published':>10}")
    for c in cols:
        lam = 1 - math.exp(coef[c])
        print(f"{c:14} {lam:14.5f} {lam_cal[c]:10.5f}")
    table = [("ml fit (this run)", fitted), ("published calibration", calib), ("training mean", [base] * len(test))]
    print(f"\nheld-out circuits: error of the predicted log S, and of S")
    out = []
    for label, pred in table:
        a, b = rmse(pred, "logS"), rmse([math.exp(x) for x in pred], "S")
        out.append({"predictor": label, "rmse_log_s": a, "rmse_s": b})
        print(f"  {label:24} {a:8.4f} {b:8.4f}")
    json.dump({"job": os.path.basename(path), "fit_circuits": len(train), "held_out": len(test), "intercept": intercept, "coefficients": coef, "lambda_fitted": {c: 1 - math.exp(coef[c]) for c in cols},
               "lambda_published": lam_cal, "held_out_error": out}, open(hw_model.stem(path) + "-rates.json", "w"), indent=1)
    print("wrote", os.path.relpath(hw_model.stem(path) + "-rates.json", hw_model.ROOT))


if __name__ == "__main__":
    main()
