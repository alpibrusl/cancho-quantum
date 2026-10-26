#!/usr/bin/env python3
"""Does a read-out scan taken just before a run explain the run, with nothing fitted?

    QSIM=path/to/qsim python3 scripts/hw_scan_model.py JOB.json SCAN.json

`JOB.json` is a `hw_spike.py run` file whose circuits and calibration `hw_model.py fetch` has saved; `SCAN.json` is a
`hw_spike.py check` file for (at least) the qubits the job used, taken shortly before it. For each circuit the table gives the distance between
the device's counts and the model's distribution (total variation; 0.01 to 0.05 is the sampling noise of 2000 shots) with the read-out
errors of the published calibration, and with those the scan measured (`idle_reads_1` for P(read 1 | 0), `after_x_reads_0` for P(read 0 | 1)).

Why: on `ibm_fez`, 2026-10-26, one qubit read 1 six times as often as its calibration said, and freeing the read-out of the qubits
in `hw_fit.py` closed most of the gap to the device (docs/hardware.md). A scan measures that directly, with no fit: if the second
column is near the sampling noise, the read-out scan is all the extra information that run needed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_fit  # noqa: E402
import hw_model  # noqa: E402


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    job = hw_fit.Job(sys.argv[1])
    scan = json.load(open(sys.argv[2]))
    measured = {int(q): (v["idle_reads_1"], v["after_x_reads_0"]) for q, v in scan["qubits"].items()}
    names = job.names()
    used = job.qubits(names)
    missing = [q for q in used if q not in measured]
    if missing:
        raise SystemExit(f"the scan has no reading for qubits {missing}")
    zero = [0.0] * 4
    before = {n: hw_fit.distance(job, n, zero) for n in names}
    calibration = dict(job.dev.readout)
    job.dev.readout = {**calibration, **{q: measured[q] for q in used}}
    after = {n: hw_fit.distance(job, n, zero) for n in names}
    print(f"{job.doc['device']}  job {job.doc['date']}  scan {scan['date']}")
    print("qubit  calibration p01 p10    scan p01 p10")
    for q in used:
        print(f"{q:5}  {calibration[q][0]:8.3f} {calibration[q][1]:6.3f}    {measured[q][0]:8.3f} {measured[q][1]:6.3f}")
    print(f"{'circuit':10} {'calibration':>12} {'scan':>8}   (model vs device, total variation)")
    for n in names:
        print(f"{n:10} {before[n]:12.4f} {after[n]:8.4f}")
    out = hw_model.stem(sys.argv[1]) + "-scan-model.json"
    json.dump({"job": os.path.basename(sys.argv[1]), "scan": os.path.basename(sys.argv[2]), "rows": [
        {"circuit": n, "model_vs_device_calibration_readout": before[n], "model_vs_device_scan_readout": after[n]} for n in names]}, open(out, "w"), indent=1)
    print("wrote", os.path.relpath(out, hw_model.ROOT))


if __name__ == "__main__":
    main()
