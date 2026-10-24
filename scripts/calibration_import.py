#!/usr/bin/env python3
"""Read a real device's published calibration into a noise profile.

    python3 scripts/calibration_import.py perth            # a snapshot shipped with qiskit-ibm-runtime
    python3 scripts/calibration_import.py --props props.json --name my_device -o profiles/my_device.json

The input is a backend-properties JSON as IBM publishes it (`qubits`, `gates`, `last_update_date`).
`qiskit-ibm-runtime` ships such snapshots for retired devices as its "fake backends"; the one used
here, `perth`, is the calibration of `ibm_perth` taken on 2024-05-27. Nothing is fetched from a live
machine and no account is needed. The output is a profile for `scripts/noise_profile.py`.

What is read, and what is changed on the way (the conversions are the part to check):

  readout     prob_meas1_prep0 -> p01, prob_meas0_prep1 -> p10, as published.
  coherence   T1, T2 (microseconds -> nanoseconds). T2 above 2 T1 is not physical and `coher` refuses
              it, so it is clipped to 2 T1 (Qiskit Aer does the same); every clip is listed.
  gate time   `sx` length per qubit; `cx` length per pair, the mean of its two directions.
  gate error  The published `gate_error` is the average gate infidelity r measured by randomized
              benchmarking, and it already contains the decay during the gate. `qsim` adds that decay
              itself (`coher`, `dur1`, `dur2`), so the depolarizing part is what is left:
                  r_dep = max(0, r - r_relax)       r_relax: the average infidelity of the idle channel
                                                    for the gate's duration, computed below
              and the depolarizing probability is p = 3 r_dep / 2 for one qubit, 5 r_dep / 4 for two
              (the average infidelity of the one- and two-qubit depolarizing channels `qsim` applies
              is 2p/3 and 4p/5). The one-qubit rate is `sx`'s (`x` is the same here); every one-qubit
              gate of a circuit gets it, as if it were one `sx`. The two-qubit rate is `cx`'s, the mean
              of its two directions.
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def relax_kraus(t1, t2, ns):
    """The Kraus operators of `qsim`'s idle channel (src/profile.cho): damping, then a phase flip."""
    gamma = 1.0 - math.exp(-ns / t1)
    rate = 1.0 / t2 - 0.5 / t1
    flip = 0.5 * (1.0 - math.exp(-ns * rate)) if rate > 0.0 else 0.0
    a = [np.array([[1, 0], [0, math.sqrt(1 - gamma)]], dtype=complex), np.array([[0, math.sqrt(gamma)], [0, 0]], dtype=complex)]
    z = np.diag([1.0, -1.0]).astype(complex)
    return [math.sqrt(1 - flip) * k for k in a] + [math.sqrt(flip) * z @ k for k in a]


def pro_fidelity(kraus):
    """Entanglement (process) fidelity of a one-qubit channel with the identity: sum |Tr K|^2 / d^2."""
    return sum(abs(np.trace(k)) ** 2 for k in kraus) / 4.0


def avg_infidelity(fpro, d):
    return 1.0 - (d * fpro + 1.0) / (d + 1.0)


def prop(items, name):
    return next((x["value"] for x in items if x["name"] == name), None)


def gate_entry(props, gate, qubits):
    return next((g for g in props["gates"] if g["gate"] == gate and g["qubits"] == qubits), None)


def convert(props, name, source):
    n = len(props["qubits"])
    coh, clipped, ro, g1, t1g = {}, [], {}, {}, {}
    f1 = {}
    for q, items in enumerate(props["qubits"]):
        t1 = prop(items, "T1") * 1000.0
        t2 = prop(items, "T2") * 1000.0
        if t2 > 2 * t1:
            clipped.append({"qubit": q, "t1_us": prop(items, "T1"), "t2_us": prop(items, "T2")})
            t2 = 2 * t1
        coh[str(q)] = [round(t1), round(t2)]
        ro[str(q)] = [prop(items, "prob_meas1_prep0"), prop(items, "prob_meas0_prep1")]
        sx = gate_entry(props, "sx", [q])
        r, ln = prop(sx["parameters"], "gate_error"), prop(sx["parameters"], "gate_length")
        t1g[str(q)] = round(ln)
        k = relax_kraus(coh[str(q)][0], coh[str(q)][1], ln)
        f1[q] = pro_fidelity(k)
        g1[str(q)] = 1.5 * max(0.0, r - avg_infidelity(f1[q], 2))
    g2, t2g, pairs_report = {}, {}, []
    for g in props["gates"]:
        if g["gate"] != "cx":
            continue
        a, b = g["qubits"]
        if a > b:
            continue
        other = gate_entry(props, "cx", [b, a])
        errs = [prop(g["parameters"], "gate_error")] + ([prop(other["parameters"], "gate_error")] if other else [])
        lens = [prop(g["parameters"], "gate_length")] + ([prop(other["parameters"], "gate_length")] if other else [])
        r, ln = sum(errs) / len(errs), sum(lens) / len(lens)
        fa = pro_fidelity(relax_kraus(coh[str(a)][0], coh[str(a)][1], ln))
        fb = pro_fidelity(relax_kraus(coh[str(b)][0], coh[str(b)][1], ln))
        r_relax = avg_infidelity(fa * fb, 4)
        g2[f"{a}-{b}"] = 1.25 * max(0.0, r - r_relax)
        t2g[f"{a}-{b}"] = round(ln)
        pairs_report.append({"pair": f"{a}-{b}", "published_error": r, "relaxation_part": r_relax, "directions_differ": len(set(errs)) > 1 or len(set(lens)) > 1})
    return {
        "name": name,
        "note": "Converted from a published calibration snapshot by scripts/calibration_import.py (see its docstring for every conversion). Not measured by this project.",
        "source": source,
        "qubits": n,
        "gate1": {"per_qubit": g1, "time_ns": {"per_qubit": t1g}},
        "gate2": {"per_pair": dict(sorted(g2.items())), "time_ns": {"per_pair": dict(sorted(t2g.items()))}},
        "readout": {"per_qubit": ro},
        "coherence": {"per_qubit": coh},
        "conversion": {"t2_clipped_to_2_t1": clipped, "two_qubit": sorted(pairs_report, key=lambda r: r["pair"])},
    }


def snapshot(backend):
    import importlib
    mod = importlib.import_module(f"qiskit_ibm_runtime.fake_provider.backends.{backend}")
    path = glob.glob(os.path.join(os.path.dirname(mod.__file__), "props_*.json"))[0]
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backend", nargs="?", help="a fake backend of qiskit-ibm-runtime, e.g. perth")
    ap.add_argument("--props", help="a backend-properties JSON file instead")
    ap.add_argument("--name")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    if not args.backend and not args.props:
        sys.exit("give a backend name or --props")
    path = args.props or snapshot(args.backend)
    props = json.load(open(path))
    name = args.name or f"{props['backend_name']}-{props['last_update_date'][:10]}"
    source = {"backend": props["backend_name"], "snapshot": props["last_update_date"],
              "origin": "IBM's published backend properties, as shipped in qiskit-ibm-runtime's fake backend" if args.backend else os.path.basename(path)}
    out = convert(props, name, source)
    text = json.dumps(out, indent=1) + "\n"
    if args.out:
        open(args.out, "w").write(text)
        print(f"wrote {args.out}: {out['qubits']} qubits, {len(out['gate2']['per_pair'])} pairs, {len(out['conversion']['t2_clipped_to_2_t1'])} T2 values clipped")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
