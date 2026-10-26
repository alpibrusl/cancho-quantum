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
FILES = [os.path.join(ROOT, "tools", "hw", f"{m}.cho") for m in "files props qasm3 model gof main".split()]


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


def build_tool(name):
    out = os.path.join(tempfile.mkdtemp(prefix=name + "-"), name)
    r = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", os.path.join(ROOT, "tools", name + ".cho"), "--std", "-o", out], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"cannot build tools/{name}.cho:\n" + r.stderr[-800:])
    return out


def main():
    hw, qsim = build(), qsim_exe()
    results = [check_relax(), check_model(hw, qsim), check_gof(hw), check_mitigate(hw, build_tool("qmitigate"))]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
