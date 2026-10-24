#!/usr/bin/env python3
"""Turn a device-style noise profile (JSON) into `qsim` operations.

    python3 scripts/noise_profile.py profiles/example_5q.json [circuit.qc]

Without a circuit it prints the profile's operations. With one it prints the circuit with
them inserted after its header (`n N` or `dm N`), so the output is a self-contained noisy
circuit. `qsim` itself reads only standard input and touches no file (`cancho authority`
says so); a profile file is read here, not there.

Format (probabilities are numbers in [0, 1]):

    {"qubits": 5,
     "gate1":   {"default": p, "per_qubit": {"0": p, ...}},     depolarizing after a one-qubit gate
     "gate2":   {"default": p, "per_pair":  {"0-1": p, ...}},   two-qubit depolarizing after a two-qubit gate
     "readout": {"default": [p01, p10], "per_qubit": {"4": [p01, p10]}}}

`p01` is the probability a true 0 is reported as 1, `p10` that a true 1 is reported as 0. A
probability becomes the fraction round(p * 10^6) / 10^6, which is what `qsim` reads
(`model1`, `model2`, `gate1err`, `gate2err`, `readerr`).
"""
import json
import sys

DEN = 1_000_000


def frac(p, what):
    if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0.0 <= p <= 1.0:
        raise ValueError(f"{what}: {p!r} is not a probability in [0, 1]")
    return round(p * DEN), DEN


def qubit_ok(q, n, what):
    if not (isinstance(q, int) and 0 <= q < n):
        raise ValueError(f"{what}: qubit {q!r} is outside 0..{n - 1}")
    return q


def operations(profile, circuit_qubits=None):
    n = profile["qubits"]
    if not isinstance(n, int) or not 1 <= n <= 20:
        raise ValueError("qubits must be an integer from 1 to 20")
    if circuit_qubits is not None and circuit_qubits > n:
        raise ValueError(f"the circuit uses {circuit_qubits} qubits and the profile describes {n}")
    ops = []
    g1 = profile.get("gate1", {})
    if "default" in g1:
        ops.append("model1 %d %d" % frac(g1["default"], "gate1.default"))
    for q, p in sorted(g1.get("per_qubit", {}).items(), key=lambda kv: int(kv[0])):
        ops.append("gate1err %d %d %d" % ((qubit_ok(int(q), n, "gate1.per_qubit"),) + frac(p, f"gate1.per_qubit.{q}")))
    g2 = profile.get("gate2", {})
    if "default" in g2:
        ops.append("model2 %d %d" % frac(g2["default"], "gate2.default"))
    for pair, p in sorted(g2.get("per_pair", {}).items()):
        a, _, b = pair.partition("-")
        a, b = qubit_ok(int(a), n, "gate2.per_pair"), qubit_ok(int(b), n, "gate2.per_pair")
        if a == b:
            raise ValueError(f"gate2.per_pair.{pair}: the two qubits are the same")
        ops.append("gate2err %d %d %d %d" % ((a, b) + frac(p, f"gate2.per_pair.{pair}")))
    ro = profile.get("readout", {})
    default = ro.get("default")
    per = {int(q): v for q, v in ro.get("per_qubit", {}).items()}
    for q in range(n):
        pair = per.get(q, default)
        if pair is not None:
            if not (isinstance(pair, list) and len(pair) == 2):
                raise ValueError(f"readout for qubit {q} must be [p01, p10]")
            ops.append("readerr %d %d %d %d %d" % ((q,) + frac(pair[0], f"readout.{q}.p01") + frac(pair[1], f"readout.{q}.p10")))
    for q in per:
        qubit_ok(q, n, "readout.per_qubit")
    return ops


def apply(profile, text):
    lines = text.splitlines()
    head = lines[0].split()
    if head[0] not in ("n", "dm"):
        raise ValueError("the circuit must start with `n <qubits>` or `dm <qubits>`")
    return "\n".join([lines[0]] + operations(profile, int(head[1])) + lines[1:]) + "\n"


def main(argv):
    if len(argv) not in (2, 3):
        sys.exit(__doc__)
    profile = json.load(open(argv[1]))
    try:
        if len(argv) == 3:
            sys.stdout.write(apply(profile, open(argv[2]).read()))
        else:
            sys.stdout.write("\n".join(operations(profile)) + "\n")
    except (ValueError, KeyError) as e:
        sys.exit(f"noise_profile: {e}")


if __name__ == "__main__":
    main(sys.argv)
