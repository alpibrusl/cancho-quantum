#!/usr/bin/env python3
"""Run `qsim`'s noise model on the circuits a real IBM device ran, and compare it with the device's counts.

    export QISKIT_IBM_TOKEN=...      # only to fetch the job's circuits and the device's calibration
    python3 scripts/hw_model.py fetch docs/data/hardware/ibm_fez-2026-10-26.json     # writes the circuits and calibration next to it
    QSIM=path/to/qsim python3 scripts/hw_model.py run docs/data/hardware/ibm_fez-2026-10-26.json

`fetch` reads the transpiled circuits back from the job recorded in the file (`job_id`) and the device's current
properties (`backend.properties()`), and saves them as OpenQASM 3 and JSON: no credentials in either.
`run` needs neither an account nor Qiskit's simulator; it needs only the files and `qsim`.

The model follows `docs/calibration.md`, gate by gate, on the circuit as the device ran it (native gates, physical
qubits renumbered to 0..k-1):

* `rz` is a virtual gate: a rotation, no noise, no time.
* `sx` becomes `rx 1/2` (the same up to a global phase), `x` stays `x`; `cz` stays `cz`.
* After a gate of duration d, `wait` on its qubits (T1/T2 decay during the gate), then depolarizing noise with the
  probability the calibration implies once that decay is taken out: 3/2 (r - r_relax) for one qubit, 5/4 (r - r_relax)
  for two (r is the published gate error, r_relax the average infidelity of the decay alone).
* A qubit that waits for a partner or for the final barrier decays too (ASAP schedule, written out as `wait`s here).
* Readout: the exact distribution comes from `dm k` + `probs`; the asymmetric readout error (prob_meas1_prep0,
  prob_meas0_prep1) is applied to it here, per qubit, because `probs` does not apply `readerr`.
* Angles are written as m*pi/2^20. A native angle is a multiple of pi/2^k already; only a few `rz` in an arbitrary
  circuit are not, and the rounding is below 3e-6 rad.
"""
import json
import math
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEN = 1 << 20


def stem(path):
    return path[: -len(".json")]


def fetch(path):
    from qiskit import qasm3
    from qiskit_ibm_runtime import QiskitRuntimeService

    doc = json.load(open(path))
    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=os.environ.get("QISKIT_IBM_TOKEN"))
    job = service.job(doc["job_id"])
    circuits = [p[0] for p in job.inputs["pubs"]]
    out = {"job_id": doc["job_id"], "device": doc["device"], "circuits": []}
    for row, qc in zip(doc["circuits"], circuits):
        out["circuits"].append({"circuit": row["circuit"], "qasm3": qasm3.dumps(qc)})
    json.dump(out, open(stem(path) + "-circuits.json", "w"), indent=1)
    props = service.backend(doc["device"]).properties().to_dict()
    props["_fetched"] = "properties as they were when fetched, which can be a later calibration than the job's"
    json.dump(props, open(stem(path) + "-props.json", "w"), default=str)
    print("wrote", stem(path) + "-circuits.json and -props.json")


def relax_infidelity(t1_us, t2_us, ns):
    from qiskit.quantum_info import average_gate_fidelity
    from qiskit_aer.noise import thermal_relaxation_error

    return 1 - average_gate_fidelity(thermal_relaxation_error(t1_us * 1e3, t2_us * 1e3, ns))


def relax_infidelity2(a, b, ns):
    from qiskit.quantum_info import average_gate_fidelity
    from qiskit_aer.noise import thermal_relaxation_error

    e = thermal_relaxation_error(a[0] * 1e3, a[1] * 1e3, ns).expand(thermal_relaxation_error(b[0] * 1e3, b[1] * 1e3, ns))
    return 1 - average_gate_fidelity(e)


class Device:
    def __init__(self, props):
        self.t1t2 = {}
        self.readout = {}
        self.gates = {}
        for q, items in enumerate(props["qubits"]):
            d = {i["name"]: i["value"] for i in items}
            if "T1" in d and "T2" in d:  # a dead qubit has none; a circuit that uses one fails on the lookup
                self.t1t2[q] = (d["T1"], min(d["T2"], 2 * d["T1"]))
            self.readout[q] = (d.get("prob_meas1_prep0", 0.0), d.get("prob_meas0_prep1", 0.0))
        for g in props["gates"]:
            p = {i["name"]: i["value"] for i in g["parameters"]}
            self.gates[(g["gate"], tuple(g["qubits"]))] = (p.get("gate_error", 0.0), p.get("gate_length", 0.0))


def frac(x):
    """x radians as `num den` meaning num*pi/den."""
    num = round(x / math.pi * DEN)
    return f"{num} {DEN}"


def build(qasm3_text, dev):
    """The `.qc` text for one circuit, the compact qubit order, and the measured physical qubits."""
    from qiskit import qasm3

    qc = qasm3.loads(qasm3_text)
    phys = sorted({qc.find_bit(q).index for i in qc.data for q in i.qubits if i.operation.name not in ("barrier",)})
    idx = {p: k for k, p in enumerate(phys)}
    lines = [f"dm {len(phys)}"]
    clock = {p: 0.0 for p in phys}

    def idle_to(p, t):
        d = round(t - clock[p])
        if d > 0:
            lines.append(f"wait {idx[p]} {d}")
        clock[p] = max(clock[p], t)

    for p in phys:
        T1, T2 = dev.t1t2[p]
        lines.append(f"coher {idx[p]} {round(T1 * 1e3)} {round(T2 * 1e3)}")
    measured = {}
    for inst in qc.data:
        op, qs = inst.operation, [qc.find_bit(q).index for q in inst.qubits]
        name = op.name
        if name == "rz":
            lines.append(f"rz {idx[qs[0]]} {frac(float(op.params[0]))}")
        elif name in ("sx", "x"):
            p = qs[0]
            r, ns = dev.gates[(name, (p,))]
            lines.append(f"rx {idx[p]} 1 2" if name == "sx" else f"x {idx[p]}")
            lines.append(f"wait {idx[p]} {round(ns)}")
            clock[p] += round(ns)
            pdep = max(0.0, 1.5 * (r - relax_infidelity(*dev.t1t2[p], ns)))
            if pdep > 0:
                lines.append(f"depol {idx[p]} {round(pdep * 1e6)} 1000000")
        elif name == "cz":
            a, b = qs
            r, ns = dev.gates.get(("cz", (a, b))) or dev.gates[("cz", (b, a))]
            start = max(clock[a], clock[b])
            idle_to(a, start)
            idle_to(b, start)
            lines.append(f"cz {idx[a]} {idx[b]}")
            lines.append(f"wait {idx[a]} {round(ns)}")
            lines.append(f"wait {idx[b]} {round(ns)}")
            clock[a] += round(ns)
            clock[b] += round(ns)
            pdep = max(0.0, 1.25 * (r - relax_infidelity2(dev.t1t2[a], dev.t1t2[b], ns)))
            if pdep > 0:
                lines.append(f"depol2 {idx[a]} {idx[b]} {round(pdep * 1e6)} 1000000")
        elif name == "barrier":
            t = max(clock.values())
            for p in phys:
                idle_to(p, t)
        elif name == "measure":
            measured[qc.find_bit(inst.clbits[0]).index] = qs[0]
        else:
            raise SystemExit(f"gate {name} is not native here")
    lines.append("probs")
    return "\n".join(lines) + "\n", phys, measured


def readout_confusion(probs, phys, measured, dev):
    """Apply per-qubit asymmetric readout error. `probs` is over the compact qubits; the result is over the classical
    bits (bit c is the measurement of measured[c]), as a dict of bitstrings with bit 0 rightmost."""
    n = len(phys)
    idx = {p: k for k, p in enumerate(phys)}
    vec = np.zeros(2**n)
    for s, v in probs.items():
        vec[int(s, 2)] = v
    t = vec.reshape([2] * n)  # axis 0 is the highest qubit
    for q in range(n):
        p01, p10 = dev.readout[phys[q]]  # P(read 1 | 0), P(read 0 | 1)
        m = np.array([[1 - p01, p10], [p01, 1 - p10]])
        ax = n - 1 - q
        t = np.moveaxis(np.tensordot(m, t, axes=([1], [ax])), 0, ax)
    # classical bit c is the measurement of physical qubit measured[c]; axis 0 of the result is the highest bit
    assert sorted(measured.values()) == sorted(phys), "an unmeasured qubit would need marginalising"
    t = np.transpose(t, [n - 1 - idx[measured[c]] for c in sorted(measured, reverse=True)])
    flat = t.reshape(-1)
    return {format(i, f"0{n}b"): float(v) for i, v in enumerate(flat) if v > 1e-12}


def tvd(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def normal(c):
    s = sum(c.values())
    return {k: v / s for k, v in c.items()}


def run(path):
    qsim = os.environ.get("QSIM", "qsim")
    doc = json.load(open(path))
    circuits = json.load(open(stem(path) + "-circuits.json"))
    props = json.load(open(stem(path) + "-props.json"))
    dev = Device(props)
    print(f"{doc['device']}  {doc['date']}  {doc['shots']} shots; calibration {props.get('last_update_date')}")
    print(f"{'circuit':9} {'qubits':>6} {'ideal-vs':>9} {'device':>8} {'Aer':>8} {'qsim':>8} {'qsim-dev':>9} {'qsim-Aer':>9}")
    rows = []
    for row, c in zip(doc["circuits"], circuits["circuits"]):
        text, phys, measured = build(c["qasm3"], dev)
        res = subprocess.run([qsim], input=text, capture_output=True, text=True, check=True)
        probs = {l.split()[1]: float(l.split()[2]) for l in res.stdout.splitlines() if l.startswith("prob ")}
        qprobs = readout_confusion(probs, phys, measured, dev)
        ideal, device, aer = row["ideal"], normal(row["device"]), normal(row["aer_noise"])
        out = {"circuit": row["circuit"], "qubits": row["qubits"], "physical_qubits": phys,
               "tvd_device": tvd(ideal, device), "tvd_aer": tvd(ideal, aer), "tvd_qsim": tvd(ideal, qprobs),
               "qsim_vs_device": tvd(qprobs, device), "qsim_vs_aer": tvd(qprobs, aer), "qsim": qprobs}
        rows.append(out)
        print(f"{row['circuit']:9} {row['qubits']:>6} {'':>9} {out['tvd_device']:>8.4f} {out['tvd_aer']:>8.4f} {out['tvd_qsim']:>8.4f} {out['qsim_vs_device']:>9.4f} {out['qsim_vs_aer']:>9.4f}")
    print("columns device/Aer/qsim: TVD from the exact ideal distribution. qsim-dev, qsim-Aer: TVD between those two distributions\n"
          "(device and Aer are 2000-shot samples, so a perfect model still shows about 0.01-0.05 against the device).")
    json.dump({"device": doc["device"], "date": doc["date"], "calibration": props.get("last_update_date"), "rows": rows},
              open(stem(path) + "-qsim.json", "w"), indent=1)
    print("wrote", os.path.relpath(stem(path) + "-qsim.json", ROOT))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("fetch", "run"):
        raise SystemExit(__doc__)
    {"fetch": fetch, "run": run}[sys.argv[1]](sys.argv[2])
