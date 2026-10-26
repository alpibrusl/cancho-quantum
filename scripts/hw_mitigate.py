#!/usr/bin/env python3
"""Read-out error mitigation (`tools/qmitigate.cho`) applied to the counts of a hardware run, and what it did to the distance from the ideal output.

    CANCHO=path/to/cancho python3 scripts/hw_mitigate.py docs/data/hardware/ibm_kingston-2026-10-26-mirror-from60.json [...]
    python3 scripts/hw_mitigate.py --readout docs/data/hardware/<device>-<time>-readout.json FILE ...    # errors measured by `hw_spike.py check`

For each circuit, the device's counts are corrected with the per-qubit read-out errors of the qubits that were measured and the
total-variation distance from the exact ideal distribution is printed before and after. The errors come from the device's
published calibration (the `-props.json` that `hw_model.py fetch` saved next to the job file) or, with `--readout`, from the
idle / after-X measurement of `hw_spike.py check`, which is taken at a time of one's choosing and does not depend on the
published calibration being current. Writes `<job>-mitigated.json` beside each file.

What it can and cannot do: it removes the part of the error that is the read-out confusion, assuming it is independent between qubits.
A mirror circuit's ideal output is all zeros, so mitigation can only help when the read-out error is a visible part of its distance.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_model  # noqa: E402
import tools_lib  # noqa: E402


def tvd(p, q):
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in set(p) | set(q))


def normal(c):
    s = sum(c.values())
    return {k: v / s for k, v in c.items()}


def one(path, readout_file):
    stem = hw_model.stem(path)
    doc = json.load(open(path))
    circuits = json.load(open(stem + "-circuits.json"))["circuits"]
    props = json.load(open(stem + "-props.json"))
    dev = hw_model.Device(props)
    measured_errors = None
    if readout_file:
        scan = json.load(open(readout_file))
        measured_errors = {int(q): (v["idle_reads_1"], v["after_x_reads_0"]) for q, v in scan["qubits"].items()}
    rows = []
    print(f"{doc['device']}  {doc['date']}  {doc['shots']} shots; read-out errors from " + (f"the scan {os.path.basename(readout_file)}" if readout_file else "the published calibration"))
    print(f"{'circuit':9} {'qubits':>6} {'before':>8} {'after':>8} {'clipped':>9}")
    for row, c in zip(doc["circuits"], circuits):
        _, phys, measured = hw_model.build(c["qasm3"], dev)
        per = {}
        for bit, q in measured.items():
            per[str(bit)] = list(measured_errors[q]) if measured_errors else list(dev.readout[q])
        counts = {k.replace(" ", ""): v for k, v in row["device"].items()}
        out = json.loads(tools_lib.run("qmitigate", json.dumps({"readout": {"per_qubit": per}, "counts": counts})))
        ideal = row["ideal"]
        before, after = tvd(ideal, normal(counts)), tvd(ideal, out["probabilities"])
        rows.append({"circuit": row["circuit"], "qubits": row["qubits"], "physical_qubits": phys, "tvd_before": before, "tvd_after": after,
                     "clipped": out["clipped"], "readout_errors": per})
        print(f"{row['circuit']:9} {row['qubits']:>6} {before:>8.4f} {after:>8.4f} {out['clipped']:>9.4f}")
    target = stem + ("-mitigated-scan.json" if readout_file else "-mitigated.json")
    json.dump({"device": doc["device"], "date": doc["date"], "shots": doc["shots"], "readout_from": os.path.basename(readout_file) if readout_file else "published calibration",
               "rows": rows}, open(target, "w"), indent=1)
    print("wrote", os.path.relpath(target, hw_model.ROOT))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--readout", help="a `hw_spike.py check` file: use the errors it measured instead of the published calibration")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    for f in args.files:
        one(f, args.readout)


if __name__ == "__main__":
    main()
