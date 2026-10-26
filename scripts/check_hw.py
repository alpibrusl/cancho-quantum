#!/usr/bin/env python3
"""The cancho program `tools/hw` (docs/hardware.md's analysis, in cancho) against the Python scripts it replaces, on the committed hardware runs.

    CANCHO=path/to/cancho QSIM=path/to/qsim python3 scripts/check_hw.py

`hw model` writes `<job>-qsim.json` as `hw_model.py run` did: for every committed run that has the circuits and calibration beside it, the tool is run on a copy of the files and its numbers
(total-variation distances and the model's distribution) are compared with the committed ones, which Python wrote: they must agree to 1e-9. The closed form of the relaxation
infidelity that the tool uses is compared with qiskit's `thermal_relaxation_error` and `average_gate_fidelity`.
"""
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
HW = os.path.join(ROOT, "docs", "data", "hardware")
FILES = [os.path.join(ROOT, "tools", "hw", f"{m}.cho") for m in "common files props qasm3 model rates gof predict fit main".split()]


def build():
    out = os.path.join(tempfile.mkdtemp(prefix="hw-"), "hw")
    r = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", *FILES, "--std", "-o", out], capture_output=True, text=True)
    if r.returncode:
        sys.exit("cannot build tools/hw:\n" + r.stderr[-1500:])
    return out


def qsim_exe():
    exe = os.environ.get("QSIM")
    if exe:
        return exe
    exe = os.path.join(tempfile.mkdtemp(prefix="qsim-"), "qsim")
    src = sorted(os.path.join(ROOT, "src", f) for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
    r = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", *src, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit("cannot build qsim:\n" + r.stderr[-800:])
    return exe


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


def check_model(hw, qsim):
    jobs = sorted(p for p in glob.glob(os.path.join(HW, "*-qsim.json")))
    worst, runs, bad = 0.0, 0, []
    for q in jobs:
        stem = q[: -len("-qsim.json")]
        if not (os.path.exists(stem + ".json") and os.path.exists(stem + "-circuits.json") and os.path.exists(stem + "-props.json")):
            continue
        d = tempfile.mkdtemp(prefix="hwrun-")
        for suffix in (".json", "-circuits.json", "-props.json"):
            shutil.copy(stem + suffix, os.path.join(d, os.path.basename(stem) + suffix))
        job = os.path.join(d, os.path.basename(stem) + ".json")
        r = subprocess.run([hw, "model", job, "--qsim", qsim], capture_output=True, text=True)
        if r.returncode:
            bad.append((os.path.basename(stem), r.stderr.strip()[:200]))
            continue
        got, want = json.load(open(job[:-5] + "-qsim.json")), json.load(open(q))
        runs += 1
        if got["device"] != want["device"] or got["date"] != want["date"] or got["calibration"] != want["calibration"] or len(got["rows"]) != len(want["rows"]):
            bad.append((os.path.basename(stem), "header or row count differs"))
            continue
        for x, y in zip(got["rows"], want["rows"]):
            if x["circuit"] != y["circuit"] or x["qubits"] != y["qubits"] or x["physical_qubits"] != y["physical_qubits"]:
                bad.append((os.path.basename(stem), x["circuit"] + ": circuit, qubits or physical qubits differ"))
                continue
            for k in ("tvd_device", "tvd_aer", "tvd_qsim", "qsim_vs_device", "qsim_vs_aer"):
                worst = max(worst, abs(x[k] - y[k]))
            for k in set(x["qsim"]) | set(y["qsim"]):
                worst = max(worst, abs(x["qsim"].get(k, 0.0) - y["qsim"].get(k, 0.0)))
    ok = not bad and worst <= 1e-9 and runs > 0
    print(f"{'ok  ' if ok else 'FAIL'} hw model on {runs} committed runs: the distances and the model's distributions agree with hw_model.py to {worst:.1e} (bound 1e-9)")
    for b in bad:
        print("   ", b)
    return ok


def check_relax():
    sys.path.insert(0, HERE)
    import hw_model

    worst = 0.0
    for t1, t2, ns in [(250, 300, 32), (100, 150, 68), (50, 40, 500), (250, 500, 84), (30, 20, 2000)]:
        a = math.exp(-ns / (t1 * 1e3))
        b = math.exp(-ns / (t2 * 1e3))
        f1 = 1 - (2 * ((1 + 2 * b + a) / 4) + 1) / 3
        worst = max(worst, abs(f1 - hw_model.relax_infidelity(t1, t2, ns)))
    for (a1, a2), (b1, b2), ns in [((250, 300), (100, 150), 68), ((50, 40), (80, 70), 84)]:
        fa = lambda t1, t2: (1 + 2 * math.exp(-ns / (t2 * 1e3)) + math.exp(-ns / (t1 * 1e3))) / 4
        f2 = 1 - (4 * fa(a1, a2) * fa(b1, b2) + 1) / 5
        worst = max(worst, abs(f2 - hw_model.relax_infidelity2((a1, a2), (b1, b2), ns)))
    ok = worst < 1e-9
    print(f"{'ok  ' if ok else 'FAIL'} the closed form of the relaxation infidelity (tools/hw/model.cho) against qiskit's: worst {worst:.1e}")
    return ok


def stage(stem_path, suffixes):
    d = tempfile.mkdtemp(prefix="hwrun-")
    for suffix in suffixes:
        shutil.copy(stem_path + suffix, os.path.join(d, os.path.basename(stem_path) + suffix))
    return os.path.join(d, os.path.basename(stem_path) + ".json")


def check_gof(hw):
    stats = os.environ.get("STATS")
    if not stats:
        print("skip hw gof: STATS (a built cancho-stats `stats`) is not set")
        return True
    want = {}
    for r in json.load(open(os.path.join(HW, "gof.json"))):
        want.setdefault(r["file"], []).append(r)
    worst, runs, bad = 0.0, 0, []
    for name, rows in sorted(want.items()):
        stem = os.path.join(HW, name[:-5])
        job = stage(stem, [".json", "-qsim.json"])
        r = subprocess.run([hw, "gof", job, "--stats", stats, "--tmp", os.path.join(os.path.dirname(job), "t-")], capture_output=True, text=True)
        if r.returncode:
            bad.append((name, r.stderr.strip()[:200]))
            continue
        got = json.load(open(job[:-5] + "-gof.json"))["rows"]
        runs += 1
        for x, y in zip(got, rows):
            if x["circuit"] != y["circuit"] or float(x["df"]) != float(y["df"]):
                bad.append((name, x["circuit"] + ": circuit or degrees of freedom differ"))
                continue
            worst = max(worst, abs(x["statistic"] - float(y["statistic"])) / max(1.0, abs(float(y["statistic"]))))
            worst = max(worst, abs(x["p_value"] - float(y["p_value"])) / max(1e-300, abs(float(y["p_value"]))))
    ok = not bad and worst <= 1e-9 and runs > 0
    print(f"{'ok  ' if ok else 'FAIL'} hw gof on {runs} committed runs: statistic, degrees of freedom and p-value agree with hw_gof.py (worst relative difference {worst:.1e})")
    for b in bad:
        print("   ", b)
    return ok


def check_mitigate(hw, qm):
    worst, runs, bad = 0.0, 0, []
    for want_path in sorted(glob.glob(os.path.join(HW, "*-mitigated.json"))):
        stem = want_path[: -len("-mitigated.json")]
        job = stage(stem, [".json", "-circuits.json", "-props.json"])
        r = subprocess.run([hw, "mitigate", job, "--qmitigate", qm], capture_output=True, text=True)
        if r.returncode:
            bad.append((os.path.basename(stem), r.stderr.strip()[:200]))
            continue
        got, want = json.load(open(job[:-5] + "-mitigated.json"))["rows"], json.load(open(want_path))["rows"]
        runs += 1
        for x, y in zip(got, want):
            if x["circuit"] != y["circuit"] or x["physical_qubits"] != y["physical_qubits"]:
                bad.append((os.path.basename(stem), x["circuit"] + ": circuit or physical qubits differ"))
                continue
            for k in ("tvd_before", "tvd_after", "clipped"):
                worst = max(worst, abs(x[k] - y[k]))
            for k, v in y["readout_errors"].items():
                worst = max(worst, abs(x["readout_errors"][k][0] - v[0]), abs(x["readout_errors"][k][1] - v[1]))
    ok = not bad and worst <= 1e-9 and runs > 0
    print(f"{'ok  ' if ok else 'FAIL'} hw mitigate on {runs} committed runs: distances before and after, the clipped mass and the read-out errors agree with hw_mitigate.py to {worst:.1e}")
    for b in bad:
        print("   ", b)
    return ok


def check_predict(hw, qsim):
    stats = os.environ.get("STATS")
    if not stats:
        print("skip hw predict: STATS (a built cancho-stats `stats`) is not set")
        return True
    stem = os.path.join(HW, "ibm_kingston-2026-10-26-mirror-from60")
    job = stage(stem, [".json", "-circuits.json", "-props.json"])
    d = os.path.dirname(job)
    # a made-up scan (the calibration's read-out, qubit 60's changed) and made-up rates (the published gate errors times 1.7): only the arithmetic is tested, not a device
    props = json.load(open(stem + "-props.json"))
    qubits = {}
    for i, items in enumerate(props["qubits"]):
        v = {x["name"]: x["value"] for x in items}
        qubits[str(i)] = {"idle_reads_1": v.get("prob_meas1_prep0", 0.0), "after_x_reads_0": v.get("prob_meas0_prep1", 0.0)}
    qubits["60"]["idle_reads_1"] = 0.0831
    lam = {}
    for g in props["gates"]:
        p = {x["name"]: x["value"] for x in g["parameters"]}
        if g["gate"] == "sx":
            lam[f"g1_{g['qubits'][0]}"] = p["gate_error"] * 1.7
        if g["gate"] == "cz":
            lam[f"cz_{g['qubits'][0]}_{g['qubits'][1]}"] = p["gate_error"] * 1.7
    json.dump({"device": "x", "date": "MADE UP", "qubits": qubits}, open(os.path.join(d, "scan.json"), "w"))
    json.dump({"job": "MADE UP", "lambda_fitted": lam}, open(os.path.join(d, "rates.json"), "w"))
    env = dict(os.environ, QSIM=qsim, STATS=stats)
    r = subprocess.run([sys.executable, os.path.join(HERE, "hw_predict.py"), job, "--scan", os.path.join(d, "scan.json"), "--rates", os.path.join(d, "rates.json")], capture_output=True, text=True, env=env)
    if r.returncode:
        print("FAIL hw predict: the Python reference failed:", r.stderr[-300:])
        return False
    want = json.load(open(job[:-5] + "-predict.json"))
    r = subprocess.run([hw, "predict", job, "--scan", os.path.join(d, "scan.json"), "--rates", os.path.join(d, "rates.json"), "--qsim", qsim, "--stats", stats, "--tmp", os.path.join(d, "t-")], capture_output=True, text=True)
    if r.returncode:
        print("FAIL hw predict:", r.stderr[-300:])
        return False
    got = json.load(open(job[:-5] + "-predict.json"))
    worst, bad = 0.0, []
    for name, rows in want["rows"].items():
        mine = got["rows"].get(name)
        if mine is None or len(mine) != len(rows):
            bad.append(name)
            continue
        for x, y in zip(mine, rows):
            worst = max(worst, abs(x["tvd"] - y["tvd"]), abs(x["p_value"] - y["p_value"]) / max(1e-300, abs(y["p_value"])))
    for name, y in want["summary"].items():
        x = got["summary"].get(name)
        if x is None or x["p_above_0.05"] != y["p_above_0.05"] or abs(x["mean_tvd"] - y["mean_tvd"]) > 1e-9:
            bad.append(name + " summary")
    ok = not bad and worst <= 1e-9
    print(f"{'ok  ' if ok else 'FAIL'} hw predict (4 variants, a made-up scan and rates) agrees with hw_predict.py: worst difference {worst:.1e}")
    for b in bad:
        print("   ", b)
    return ok


def synthetic_rates_job(d):
    """A `--set rates` job made up from the kingston calibration: gate counts at random, the survival of each circuit from the published errors times 1.3, the zeros sampled (2000 shots)."""
    import random

    props = json.load(open(os.path.join(HW, "ibm_kingston-2026-10-26-mirror-from60-props.json")))
    err = {}
    for g in props["gates"]:
        p = {x["name"]: x["value"] for x in g["parameters"]}
        if g["gate"] == "sx":
            err[("g1", g["qubits"][0])] = p["gate_error"]
        if g["gate"] == "cz":
            err[("cz", tuple(sorted(g["qubits"])))] = p["gate_error"]
    line = [60, 61, 62, 63, 56]
    rnd = random.Random(3)
    rows = []
    for i in range(100):
        cz = {f"{min(a, b)}-{max(a, b)}": 2 * rnd.randint(0, 30) for a, b in zip(line, line[1:])}
        one = {str(q): 2 * rnd.randint(0, 40) for q in line}
        logs = sum(v * math.log(1 - 1.3 * err[("cz", tuple(sorted(map(int, k.split("-")))))]) for k, v in cz.items())
        logs += sum(v * math.log(1 - 1.3 * err[("g1", int(k))]) for k, v in one.items())
        for q in line:
            v = {x["name"]: x["value"] for x in props["qubits"][q]}
            logs += math.log(1 - v["prob_meas1_prep0"])
        pz = math.exp(logs)
        zeros = sum(1 for _ in range(2000) if rnd.random() < pz)
        rows.append({"circuit": f"r{i:03d}", "qubits": 5, "ideal": {"00000": 1.0}, "device": {"00000": zeros, "00001": 2000 - zeros}, "gates": {"sx_x": one, "cz": cz}})
    job = os.path.join(d, "rates-job.json")
    json.dump({"device": "ibm_kingston", "date": "MADE UP", "shots": 2000, "line": line, "circuits": rows}, open(job, "w"))
    shutil.copy(os.path.join(HW, "ibm_kingston-2026-10-26-mirror-from60-props.json"), os.path.join(d, "rates-job-props.json"))
    return job


def check_rates(hw):
    ml = os.environ.get("ML")
    if not ml:
        print("skip hw rates: ML (a built cancho-ml `ml`) is not set")
        return True
    d = tempfile.mkdtemp(prefix="hwrates-")
    job = synthetic_rates_job(d)
    env = dict(os.environ, ML=ml)
    r = subprocess.run([sys.executable, os.path.join(HERE, "hw_rates.py"), job], capture_output=True, text=True, env=env)
    if r.returncode:
        print("FAIL hw rates: the Python reference failed:", r.stderr[-300:])
        return False
    want = json.load(open(job[:-5] + "-rates.json"))
    os.remove(job[:-5] + "-rates.json")
    r = subprocess.run([hw, "rates", job, "--ml", ml, "--tmp", os.path.join(d, "t-")], capture_output=True, text=True)
    if r.returncode:
        print("FAIL hw rates:", r.stderr[-300:], r.stdout[-300:])
        return False
    got = json.load(open(job[:-5] + "-rates.json"))
    worst = abs(got["intercept"] - want["intercept"])
    for key in ("coefficients", "lambda_fitted", "lambda_published"):
        for k, v in want[key].items():
            worst = max(worst, abs(got[key][k] - v))
    for x, y in zip(got["held_out_error"], want["held_out_error"]):
        if x["predictor"] != y["predictor"]:
            worst = 1.0
        worst = max(worst, abs(x["rmse_log_s"] - y["rmse_log_s"]), abs(x["rmse_s"] - y["rmse_s"]))
    ok = worst <= 1e-9 and got["fit_circuits"] == want["fit_circuits"] and got["held_out"] == want["held_out"]
    best = {x["predictor"]: x["rmse_log_s"] for x in got["held_out_error"]}
    print(f"{'ok  ' if ok else 'FAIL'} hw rates on a made-up run of 100 circuits agrees with hw_rates.py to {worst:.1e}; held-out error of log S: " + ", ".join(f"{k} {v:.4f}" for k, v in best.items()))
    return ok


def check_fit(hw, qsim):
    """`hw fit` (cancho-opt's `opt minimize` on `hw misfit`) against the committed result of `hw_fit.py`: the fez morning run fitted on three circuits and tested on the two other runs."""
    opt = os.environ.get("OPT")
    if not opt:
        print("skip hw fit: OPT (a built cancho-opt `opt`) is not set")
        return True
    base = "ibm_fez-2026-10-26-mirror-from60"
    want = json.load(open(os.path.join(HW, f"fit-global-{base}.json")))
    stems = [os.path.join(HW, base), os.path.join(HW, base + "-1000"), os.path.join(HW, base + "-1030")]
    d = tempfile.mkdtemp(prefix="hwfit-")
    paths = []
    for st in stems:
        for suffix in (".json", "-circuits.json", "-props.json"):
            shutil.copy(st + suffix, os.path.join(d, os.path.basename(st) + suffix))
        paths.append(os.path.join(d, os.path.basename(st) + ".json"))
    r = subprocess.run([hw, "fit", paths[0], "--fit-circuits", ",".join(want["fit_circuits"]), "--test", paths[1], paths[2], "--tag", "chk", "--opt", opt, "--qsim", qsim, "--self", hw], capture_output=True, text=True)
    if r.returncode:
        print("FAIL hw fit:", r.stderr[-300:])
        return False
    got = json.load(open(os.path.join(d, f"fit-chk-{base}.json")))
    bad = []
    if sorted(got["fit_circuits"]) != sorted(want["fit_circuits"]):
        bad.append("fit_circuits")
    if got["evaluations"] != want["evaluations"]:
        bad.append(f"evaluations {got['evaluations']} != {want['evaluations']}")
    worst = 0.0
    for key in ("misfit_before", "misfit_after"):
        worst = max(worst, abs(got[key] - want[key]))
    for name in ("decay", "depol1", "depol2", "readout"):
        worst = max(worst, abs(got["factors"][name] / want["factors"][name] - 1.0))
    rows = {(r_["file"], r_["circuit"]): r_ for r_ in want["rows"]}
    mine = {(r_["file"], r_["circuit"]): r_ for r_ in got["rows"]}
    if set(rows) != set(mine):
        bad.append("rows")
    else:
        for k, v in rows.items():
            if mine[k]["role"] != v["role"]:
                bad.append(f"role of {k}")
            for f in ("model_vs_device_calibration", "model_vs_device_fitted"):
                worst = max(worst, abs(mine[k][f] - v[f]))
    ok = not bad and worst <= 1e-9
    print(f"{'ok  ' if ok else 'FAIL'} hw fit (fez, 3 circuits, tested on 2 other runs: {len(rows)} rows) agrees with the committed hw_fit.py result: same number of evaluations, worst difference {worst:.1e}" + ("" if ok else f"  {bad}"))
    return ok


def build_tool(name):
    out = os.path.join(tempfile.mkdtemp(prefix=name + "-"), name)
    r = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", os.path.join(ROOT, "tools", name + ".cho"), "--std", "-o", out], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"cannot build tools/{name}.cho:\n" + r.stderr[-800:])
    return out


def main():
    hw, qsim = build(), qsim_exe()
    results = [check_relax(), check_model(hw, qsim), check_gof(hw), check_mitigate(hw, build_tool("qmitigate")), check_predict(hw, qsim), check_rates(hw), check_fit(hw, qsim)]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
