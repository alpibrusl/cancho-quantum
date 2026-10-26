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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "data", "hardware")
CIRCUITS = ["bell", "ghz3", "ghz5", "ghz7", "toffoli", "qft4", "random5"]


MIRROR = ["ghzm3", "ghzm5", "ghzm7", "rmir5_d2", "rmir5_d4", "rmir5_d8"]


def mirror(name):
    """A circuit U, a barrier, then U inverse: the ideal output is all zeros, so the distance from it is the error the
    circuit accumulated (and a model that is blind to correlated noise shows it). `ghzm<n>` is an n-qubit GHZ state and its
    inverse; `rmir5_d<k>` is k layers of random one-qubit gates and `cx` on a line of 5 qubits (fixed seed) and its inverse."""
    import random

    from qiskit import QuantumCircuit

    if name.startswith("ghzm"):
        n = int(name[4:])
        u = QuantumCircuit(n)
        u.h(0)
        for i in range(n - 1):
            u.cx(i, i + 1)
    else:
        n, depth = 5, int(name.split("_d")[1])
        rng = random.Random(2026)
        u = QuantumCircuit(n)
        for layer in range(depth):
            for q in range(n):
                getattr(u, rng.choice(["h", "s", "t", "sx", "x"]))(q)
            for q in range(layer % 2, n - 1, 2):
                u.cx(q, q + 1)
    qc = QuantumCircuit(u.num_qubits)
    qc.compose(u, inplace=True)
    qc.barrier()
    qc.compose(u.inverse(), inplace=True)
    qc.measure_all()
    return qc


def line_from(backend, start, n):
    """n connected qubits, a simple path in the coupling map beginning at `start` (depth-first, so it exists whenever one does)."""
    adj = {}
    for a, b in backend.coupling_map.get_edges():
        adj.setdefault(a, []).append(b)

    def walk(path):
        if len(path) == n:
            return path
        for nxt in sorted(adj.get(path[-1], [])):
            if nxt not in path and (found := walk(path + [nxt])):
                return found
        return None

    path = walk([start])
    if path is None:
        raise SystemExit(f"no line of {n} connected qubits from {start}")
    return path


def load(name):
    from qiskit import QuantumCircuit

    if name in MIRROR:
        return mirror(name)

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


BAD = 0.15    # a qubit that reads the wrong value this often is broken, whatever its calibration says
WEAK = 0.05   # and this often is worth a look


def classify(p1_idle, p0_flipped):
    """`bad`, `weak` or `ok`, from how often an idle qubit reads 1 and how often one prepared in 1 reads 0."""
    worst = max(p1_idle, p0_flipped)
    return "bad" if worst > BAD else "weak" if worst > WEAK else "ok"


def scan(backend, qubits, shots, stand_in=False):
    """Pre-flight: measure `qubits` idle, then each after an X gate, in one job of two circuits (a few seconds of the plan's time).

    Returns {qubit: (P(read 1 | idle), P(read 0 | prepared 1))}. A qubit stuck at 1 shows in the first number, one stuck at 0 in the
    second; the calibration the device publishes did not warn of either (docs/hardware.md, kingston qubit 0)."""
    from qiskit import QuantumCircuit
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    qubits = sorted(qubits)
    circuits = []
    for flip in (False, True):
        qc = QuantumCircuit(backend.num_qubits, len(qubits))
        if flip:
            for q in qubits:
                qc.x(q)
        for k, q in enumerate(qubits):
            qc.measure(q, k)
        circuits.append(qc)
    isa = generate_preset_pass_manager(backend=backend, optimization_level=0, initial_layout=list(range(backend.num_qubits))).run(circuits)
    if stand_in:
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel

        sim = AerSimulator(noise_model=NoiseModel.from_backend(backend), seed_simulator=3)
        counts = [sim.run(c, shots=shots).result().get_counts() for c in isa]
    else:
        from qiskit_ibm_runtime import SamplerV2

        result = SamplerV2(mode=backend).run(isa, shots=shots).result()
        counts = [r.data.c.get_counts() for r in result]
    out = {}
    for k, q in enumerate(qubits):
        def ones(c):  # how often clbit k reads 1 (bit k is k places from the right of a key)
            total = sum(c.values())
            return sum(v for key, v in c.items() if key.replace(" ", "")[::-1][k] == "1") / total
        out[q] = (ones(counts[0]), 1.0 - ones(counts[1]))
    return out


def report_scan(result):
    bad = sorted(q for q, (a, b) in result.items() if classify(a, b) == "bad")
    weak = sorted(q for q, (a, b) in result.items() if classify(a, b) == "weak")
    print(f"{len(result)} qubits read idle and after X: {len(result) - len(bad) - len(weak)} ok, {len(weak)} weak (> {WEAK:.0%}), {len(bad)} bad (> {BAD:.0%})")
    for q in bad + weak:
        a, b = result[q]
        print(f"  qubit {q:3d}  {classify(a, b):4}  reads 1 idle {a:6.1%}   reads 0 after X {b:6.1%}")
    return bad, weak


def check(args):
    """`hw_spike.py check`: scan the qubits of a device (all of them by default) and write what was found."""
    backend, stand_in = open_backend(args)
    qubits = [int(x) for x in args.qubits.split(",")] if args.qubits else list(range(backend.num_qubits))
    print("device:", backend.name, "qubits scanned:", len(qubits))
    result = scan(backend, qubits, args.shots, stand_in)
    bad, weak = report_scan(result)
    when = datetime.datetime.now(datetime.timezone.utc)
    doc = {"device": backend.name, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "shots": args.shots, "stand_in": stand_in,
           "thresholds": {"bad": BAD, "weak": WEAK}, "bad": bad, "weak": weak,
           "qubits": {str(q): {"idle_reads_1": a, "after_x_reads_0": b} for q, (a, b) in result.items()}}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{backend.name}-{when.strftime('%Y-%m-%d-%H%M')}-readout{'-standin' if stand_in else ''}.json")
    json.dump(doc, open(path, "w"), indent=1)
    print("wrote", os.path.relpath(path, ROOT))
    return 1 if bad else 0


def open_backend(args):
    if args.fake:
        from qiskit_ibm_runtime import fake_provider

        return getattr(fake_provider, args.fake)(), True
    from qiskit_ibm_runtime import QiskitRuntimeService

    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=os.environ.get("QISKIT_IBM_TOKEN"))
    return (service.backend(args.backend) if args.backend else service.least_busy(operational=True, simulator=False, min_num_qubits=7)), False


def used_qubits(isa):
    """The physical qubits any gate of the transpiled circuits touches."""
    used = set()
    for t in isa:
        for inst in t.data:
            if inst.operation.name != "barrier":
                used.update(t.find_bit(q).index for q in inst.qubits)
    return used


def gate_counts(t):
    """What the transpiled circuit `t` asks of each physical qubit and pair: `sx` and `x` per qubit (`rz` is virtual and free), `cz` per pair."""
    one, two = {}, {}
    for inst in t.data:
        name = inst.operation.name
        qs = [t.find_bit(q).index for q in inst.qubits]
        if name in ("sx", "x"):
            one[qs[0]] = one.get(qs[0], 0) + 1
        elif name == "cz":
            key = f"{min(qs)}-{max(qs)}"
            two[key] = two.get(key, 0) + 1
    return {"sx_x": {str(q): v for q, v in sorted(one.items())}, "cz": two}


def run_rates(args):
    """`--set rates`: many random mirror circuits of native gates on one line of qubits, for the gate-rate regression of docs/rates-regression.md."""
    import random

    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    import rates_lib

    n = args.width
    backend, stand_in = open_backend(args)
    start = args.start if args.start is not None else 0
    line = line_from(backend, start, n)
    print("device:", backend.name, "qubits:", backend.num_qubits, "line:", line, "circuits:", args.circuits)
    rnd = random.Random(args.seed)
    design = rates_lib.design(rnd, n, args.circuits)
    circuits = [rates_lib.qiskit_circuit(ops, n) for ops, _, _ in design]
    # level 0: the transpiler only maps the gates onto the device's (they are native up to `sxdg`, which becomes rz sx rz) and keeps the circuit as it is
    pm = generate_preset_pass_manager(backend=backend, optimization_level=0, seed_transpiler=args.seed, initial_layout=line)
    isa = pm.run(circuits)
    if not args.no_preflight:
        print(f"pre-flight: {len(line)} qubits, read idle and after X")
        bad, weak = report_scan(scan(backend, line, 1000, stand_in))
        if bad:
            raise SystemExit(f"qubits {bad} are broken: choose another --start, or run with --no-preflight to measure them anyway")
    if stand_in:
        from qiskit_aer import AerSimulator
        from qiskit_aer.noise import NoiseModel

        sim = AerSimulator(noise_model=NoiseModel.from_backend(backend), seed_simulator=2)
        counts = [sim.run(c, shots=args.shots).result().get_counts() for c in isa]
        job_ids = []
    else:
        from qiskit_ibm_runtime import SamplerV2

        counts, job_ids = [], []
        for k in range(0, len(isa), 100):       # jobs of 100 circuits
            job = SamplerV2(mode=backend).run(isa[k:k + 100], shots=args.shots)
            job_ids.append(job.job_id())
            print("job", job.job_id(), f"({k + 1} to {min(k + 100, len(isa))}) submitted; waiting")
            counts += [r.data.meas.get_counts() for r in job.result()]
    rows = []
    for i, (c, t) in enumerate(zip(counts, isa)):
        rows.append({"circuit": f"r{i:03d}", "qubits": n, "ideal": {"0" * n: 1.0}, "device": pad(c, n), "transpiled": {"two_qubit_gates": sum(1 for g in t.data if g.operation.name == "cz"), "ops": dict(t.count_ops())},
                     "gates": gate_counts(t)})
    when = datetime.datetime.now(datetime.timezone.utc)
    doc = {"device": backend.name, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "shots": args.shots, "job_id": job_ids[0] if job_ids else None, "job_ids": job_ids,
           "stand_in": stand_in, "note": "NOT hardware: Aer with the fake device's noise stands in for it" if stand_in else "real device", "set": "rates",
           "line": line, "seed": args.seed, "circuits": rows}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{backend.name}-{when.strftime('%Y-%m-%d-%H%M')}-rates-from{start}{'-standin' if stand_in else ''}.json")
    json.dump(doc, open(path, "w"), indent=1)
    if stand_in:       # a real run's calibration is fetched afterwards (hw_model.py fetch); a stand-in has it at once
        json.dump(backend.properties().to_dict(), open(path[: -len(".json")] + "-props.json", "w"), default=str)
    print("wrote", os.path.relpath(path, ROOT))


def run(args):
    if args.set == "rates":
        return run_rates(args)
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel

    names = MIRROR if args.set == "mirror" else CIRCUITS
    circuits = [load(n) for n in names]
    backend, stand_in = open_backend(args)
    print("device:", backend.name, "qubits:", backend.num_qubits)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=args.level, seed_transpiler=args.seed)
    if args.start is None:
        isa = pm.run(circuits)
    else:  # one line of connected qubits from --start, as long as each circuit needs
        isa = [generate_preset_pass_manager(backend=backend, optimization_level=args.level, seed_transpiler=args.seed,
                                            initial_layout=line_from(backend, args.start, c.num_qubits)).run(c) for c in circuits]

    if not args.no_preflight:
        used = sorted(used_qubits(isa))
        print(f"pre-flight: {len(used)} qubits the circuits use, read idle and after X")
        bad, weak = report_scan(scan(backend, used, 1000, stand_in))
        if bad:
            raise SystemExit(f"qubits {bad} are broken: choose another --start or --seed, or run with --no-preflight to measure them anyway")

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
    for name, qc, c, a, t in zip(names, circuits, counts, aer_counts, isa):
        n = qc.num_qubits
        rows.append({
            "circuit": name,
            "qubits": n,
            "ideal": ideal(qc),
            "device": pad(c, n),
            "aer_noise": pad(a, n),
            "transpiled": {"depth": t.depth(), "two_qubit_gates": sum(1 for i in t.data if len(i.qubits) == 2 and i.operation.name != "barrier"),
                           "ops": dict(t.count_ops())},
        })
    when = datetime.datetime.now(datetime.timezone.utc)
    doc = {"device": backend.name, "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "shots": args.shots, "job_id": job_id,
           "optimization_level": args.level, "stand_in": stand_in if stand_in else False,
           "note": "NOT hardware: Aer with the fake device's noise stands in for it" if stand_in else "real device",
           "circuits": rows}
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{backend.name}-{when.strftime('%Y-%m-%d')}{'-' + args.set if args.set != 'spike' else ''}{'-from' + str(args.start) if args.start is not None else ''}{'-standin' if stand_in else ''}.json")
    if os.path.exists(path):  # a second run on the same day keeps the first: the time of day goes into the name
        path = path[: -len(".json")] + when.strftime("-%H%M") + ".json"
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
    r.add_argument("--set", choices=["spike", "mirror", "rates"], default="spike", help="spike: the seven circuits of tests/qasm; mirror: circuits followed by their inverse; rates: many random native-gate mirror circuits for the gate-rate regression")
    r.add_argument("--circuits", type=int, default=300, help="with --set rates: how many circuits")
    r.add_argument("--width", type=int, default=5, help="with --set rates: how many qubits on the line")
    r.add_argument("--seed", type=int, default=1, help="transpiler seed (another seed can mean another placement)")
    r.add_argument("--start", type=int, help="place each circuit on a line of connected qubits beginning here (default: the transpiler chooses)")
    r.add_argument("--no-preflight", action="store_true", help="skip the read-out check of the qubits the circuits use (it costs one more job of two circuits)")
    r.add_argument("--level", type=int, default=1, help="Qiskit transpiler optimization level")
    c = sub.add_parser("check", help="read every qubit of a device idle and after X, and name the broken ones")
    c.add_argument("--backend")
    c.add_argument("--fake")
    c.add_argument("--shots", type=int, default=1000)
    c.add_argument("--qubits", help="comma-separated list (default: all)")
    a = sub.add_parser("analyze")
    a.add_argument("file")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args)
    elif args.cmd == "check":
        return check(args)
    else:
        analyze_doc(json.load(open(args.file)))


if __name__ == "__main__":
    sys.exit(main())
