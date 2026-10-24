#!/usr/bin/env python3
"""Run a few of the repository's circuits on a real IBM quantum computer and compare the counts with the simulations.

    # once: a free account at https://quantum.cloud.ibm.com (see docs/hardware.md), then
    export QISKIT_IBM_TOKEN=...            # your API key; never commit it
    python3 scripts/hw_spike.py run --shots 2000            # least busy real device; writes docs/data/hardware/<device>-<date>.json
    python3 scripts/hw_spike.py analyze docs/data/hardware/<file>.json

    python3 scripts/hw_spike.py run --fake FakePerth        # no account: Aer + the fake device's noise stands in for the hardware
                                                            # (tests this script; says so in the file)

`run` takes tests/qasm/<name>.qasm (the OpenQASM tools/qcconv.cho writes from tests/diff/*.qc), adds the measurements,
lets Qiskit's transpiler fit the circuit to the device (we do not transpile; docs/hardware.md), and submits all circuits as
one job. It records, for each circuit, the counts the device returned, the exact ideal distribution, and what Aer gives
with the noise model Qiskit builds from the same device (`NoiseModel.from_backend`), so that the comparison needs no account.

`analyze` prints the total-variation distance (half the L1 distance of two distributions) from the ideal one of:
the device's counts; Aer's noisy counts; and, as the floor, a sample of the ideal distribution of the same size (what perfect
hardware would still show, from finite shots). A device number far above Aer's means the noise model misses something.

The free plan allows about 10 minutes of device time per 28 days. These circuits are a few seconds in all.
"""
import argparse
import datetime
import json
import os
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "data", "hardware")
CIRCUITS = ["bell", "ghz3", "ghz5", "ghz7", "toffoli", "qft4", "random5"]


def load(name):
    from qiskit import QuantumCircuit

    qc = QuantumCircuit.from_qasm_file(os.path.join(ROOT, "tests", "qasm", name + ".qasm"))
    # the files declare a classical register and never use it: start from the gates alone, measured into one register `meas`
    bare = QuantumCircuit(qc.num_qubits)
    for inst in qc.data:
        bare.append(inst.operation, [bare.qubits[qc.find_bit(q).index] for q in inst.qubits])
    bare.measure_all()
    return bare


def ideal(qc):
    from qiskit.quantum_info import Statevector

    bare = qc.remove_final_measurements(inplace=False)
    probs = Statevector(bare).probabilities_dict()
    return {k: float(v) for k, v in probs.items() if v > 1e-12}


def pad(counts, n):
    return {format(int(k.replace(" ", ""), 2), f"0{n}b"): v for k, v in counts.items()}


def run(args):
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel

    circuits = [load(n) for n in CIRCUITS]
    if args.fake:
        from qiskit_ibm_runtime import fake_provider

        backend = getattr(fake_provider, args.fake)()
        stand_in = True
    else:
        from qiskit_ibm_runtime import QiskitRuntimeService

        service = QiskitRuntimeService(channel="ibm_quantum_platform", token=os.environ.get("QISKIT_IBM_TOKEN"))
        backend = service.backend(args.backend) if args.backend else service.least_busy(operational=True, simulator=False, min_num_qubits=7)
        stand_in = False
    print("device:", backend.name, "qubits:", backend.num_qubits)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=args.level, seed_transpiler=1)
    isa = pm.run(circuits)

    noisy = AerSimulator(noise_model=NoiseModel.from_backend(backend), seed_simulator=1)
    aer_counts = [noisy.run(c, shots=args.shots).result().get_counts() for c in isa]

    if stand_in:
        counts = [AerSimulator(noise_model=NoiseModel.from_backend(backend), seed_simulator=2).run(c, shots=args.shots).result().get_counts() for c in isa]
        job_id = None
    else:
        from qiskit_ibm_runtime import SamplerV2

        job = SamplerV2(mode=backend).run(isa, shots=args.shots)
        job_id = job.job_id()
        print("job", job_id, "submitted; waiting (the queue may take minutes to hours)")
        result = job.result()
        counts = [r.data.meas.get_counts() for r in result]

    rows = []
    for name, qc, c, a, t in zip(CIRCUITS, circuits, counts, aer_counts, isa):
        n = qc.num_qubits
        rows.append({
            "circuit": name,
            "qubits": n,
            "ideal": ideal(qc),
            "device": pad(c, n),
            "aer_noise": pad(a, n),
            "transpiled": {"depth": t.depth(), "two_qubit_gates": sum(1 for i in t.data if len(i.qubits) == 2),
                           "ops": dict(t.count_ops())},
        })
    when = datetime.datetime.now(datetime.timezone.utc)
    doc = {"device": backend.name, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "shots": args.shots, "job_id": job_id,
           "optimization_level": args.level, "stand_in": stand_in if stand_in else False,
           "note": "NOT hardware: Aer with the fake device's noise stands in for it" if stand_in else "real device",
           "circuits": rows}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{backend.name}-{when.strftime('%Y-%m-%d')}{'-standin' if stand_in else ''}.json")
    json.dump(doc, open(path, "w"), indent=1)
    print("wrote", os.path.relpath(path, ROOT))
    analyze_doc(doc)


def tvd(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def normal(counts):
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


def analyze_doc(doc):
    rng = np.random.default_rng(7)
    print(f"{doc['device']}  {doc['date']}  {doc['shots']} shots  ({doc['note']})")
    print(f"{'circuit':10} {'qubits':>6} {'2q gates':>8} {'device':>8} {'Aer noise':>10} {'floor':>8}")
    for r in doc["circuits"]:
        ideal_p = r["ideal"]
        keys = sorted(ideal_p)
        sample = rng.multinomial(doc["shots"], np.array([ideal_p[k] for k in keys]) / sum(ideal_p.values()))
        floor = tvd(ideal_p, normal(dict(zip(keys, sample))))
        print(f"{r['circuit']:10} {r['qubits']:>6} {r['transpiled']['two_qubit_gates']:>8} {tvd(ideal_p, normal(r['device'])):>8.4f} {tvd(ideal_p, normal(r['aer_noise'])):>10.4f} {floor:>8.4f}")
    print("TVD from the exact ideal distribution; 'floor' is what perfect hardware shows from finite shots.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", help="device name (default: the least busy real device with 7 or more qubits)")
    r.add_argument("--fake", help="a fake device class (e.g. FakePerth): test the script without an account")
    r.add_argument("--shots", type=int, default=2000)
    r.add_argument("--level", type=int, default=1, help="Qiskit transpiler optimization level")
    a = sub.add_parser("analyze")
    a.add_argument("file")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args)
    else:
        analyze_doc(json.load(open(args.file)))


if __name__ == "__main__":
    sys.exit(main())
