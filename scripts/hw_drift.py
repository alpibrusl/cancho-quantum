#!/usr/bin/env python3
"""Run the mirror circuits on a real device every hour and record how far the device is from the noise model, hour by hour.

    export QISKIT_IBM_TOKEN=...; export QSIM=path/to/qsim
    python3 scripts/hw_drift.py --hours 24 --device ibm_fez --also ibm_kingston --also-every 3

Each round runs `hw_spike.py run --set mirror --start 60` (about 5 s of the free plan's 600 s per 28 days), then
`hw_model.py fetch` and `run` on the file it wrote, and appends one row per circuit to
docs/data/hardware/drift-<device>-<date>.csv: time, calibration time, the device's TVD from all zeros, Aer's and `qsim`'s.
It stops early if fewer than --reserve seconds of the plan are left. The job file of every round is kept.
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "data", "hardware")


def remaining_seconds():
    from qiskit_ibm_runtime import QiskitRuntimeService

    s = QiskitRuntimeService(channel="ibm_quantum_platform", token=os.environ.get("QISKIT_IBM_TOKEN"))
    return s.usage()["usage_remaining_seconds"]


def sh(*cmd):
    r = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def one_round(device, start):
    code, out = sh(os.path.join(HERE, "hw_spike.py"), "run", "--set", "mirror", "--backend", device, "--start", str(start))
    wrote = [l.split()[1] for l in out.splitlines() if l.startswith("wrote ")]
    if code or not wrote:
        print(f"[{datetime.datetime.now():%H:%M}] {device}: run failed: {out[-300:]}", flush=True)
        return
    path = os.path.join(HERE, "..", wrote[0])
    for step in ("fetch", "run"):
        code, out = sh(os.path.join(HERE, "hw_model.py"), step, path)
        if code:
            print(f"[{datetime.datetime.now():%H:%M}] {device}: hw_model {step} failed: {out[-300:]}", flush=True)
            return
    stem = path[: -len(".json")]
    model = json.load(open(stem + "-qsim.json"))
    csv_path = os.path.join(OUT, f"drift-{device}-{datetime.date.today()}.csv")
    new = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["job_file", "job_time_utc", "calibration", "circuit", "device_tvd", "aer_tvd", "qsim_tvd"])
        for r in model["rows"]:
            w.writerow([os.path.basename(path), model["date"], model["calibration"], r["circuit"],
                        round(r["tvd_device"], 4), round(r["tvd_aer"], 4), round(r["tvd_qsim"], 4)])
    print(f"[{datetime.datetime.now():%H:%M}] {device}: {os.path.basename(path)} recorded", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--device", default="ibm_fez")
    ap.add_argument("--also", help="a second device, run every --also-every rounds, as a control")
    ap.add_argument("--also-every", type=int, default=3)
    ap.add_argument("--start", type=int, default=60)
    ap.add_argument("--reserve", type=int, default=120, help="stop when fewer seconds of the plan remain")
    a = ap.parse_args()
    for k in range(a.hours):
        t0 = time.time()
        left = remaining_seconds()
        if left < a.reserve:
            print(f"stopping: {left} s of the plan left", flush=True)
            return
        one_round(a.device, a.start)
        if a.also and k % a.also_every == 0:
            one_round(a.also, a.start)
        if k < a.hours - 1:
            time.sleep(max(0, 3600 - (time.time() - t0)))
    print("done", flush=True)


if __name__ == "__main__":
    main()
