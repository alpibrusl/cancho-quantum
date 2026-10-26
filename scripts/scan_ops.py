#!/usr/bin/env python3
"""REFERENCE IMPLEMENTATION of `tools/qscan.cho`: the oracle it is differentially tested against (`scripts/check_scan.py`).

    python3 scripts/scan_ops.py < scan.json          (or with a first line `qubits P0 P1 ...`)

Turns a `hw_spike.py check` file into `qsim` `readerr` operations, as the tool's header describes. Probabilities become round(p * 10^6) / 10^6, half to even.
"""
import json
import sys

DEN = 1_000_000


class Refused(Exception):
    pass


def prob(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0.0 <= x <= 1.0:
        raise Refused("a qubit's idle_reads_1 and after_x_reads_0 must be numbers from 0 to 1")
    return round(float(x) * DEN)          # Python's round is half to even, as qprofile's


def plain(text):
    return text.isdigit() and text.isascii() and len(text) <= 6


def ops(text):
    order = None
    if text.startswith("qubits "):
        first, _, text = text.partition("\n")
        words = first.split()[1:]
        if len(words) > 20 or any(not plain(w) for w in words):
            raise Refused("the first line must be `qubits` and up to 20 device qubit numbers")
        order = [int(w) for w in words]
        text = "\n" + text
    try:
        doc = json.loads(text)
    except ValueError:
        raise Refused("the input is not a JSON object")
    if not isinstance(doc, dict):
        raise Refused("the input is not a JSON object")
    qs = doc.get("qubits")
    if not isinstance(qs, dict):
        raise Refused("`qubits` must be an object of qubit: {idle_reads_1, after_x_reads_0}")
    by = {}
    for k, v in qs.items():
        if plain(k) and int(k) not in by:       # the first entry for a number wins, as the tool takes the first
            by[int(k)] = v
    out = []
    n = len(order) if order else 20
    for q in range(n):
        p = order[q] if order else q
        if p not in by:
            if order:
                raise Refused("a qubit named on the first line is not in the scan")
            continue
        v = by[p]
        if not isinstance(v, dict):
            raise Refused("a qubit's idle_reads_1 and after_x_reads_0 must be numbers from 0 to 1")
        a, b = prob(v.get("idle_reads_1")), prob(v.get("after_x_reads_0"))
        out.append(f"readerr {q} {a} {DEN} {b} {DEN}")
    return "".join(l + "\n" for l in out)


def main():
    try:
        sys.stdout.write(ops(sys.stdin.read()))
    except Refused as e:
        sys.stderr.write(f"qscan: {e}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
