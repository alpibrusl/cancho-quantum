#!/usr/bin/env python3
"""REFERENCE IMPLEMENTATION of `tools/qmitigate.cho`, the oracle it is differentially tested against (`scripts/check_tools.py`).

    python3 scripts/mitigate.py < run.json

Read-out error mitigation: the counts become a distribution and each qubit's confusion matrix [[1-p01, p10], [p01, 1-p10]] is
inverted along that qubit; negative entries are set to 0 and the rest scaled to sum to 1 (`clipped` is the removed negative mass).
The input and output formats are those documented at the top of `tools/qmitigate.cho`. Also used by `scripts/hw_mitigate.py` on the
counts of a hardware run.
"""
import json
import sys


class Refused(Exception):
    pass


def mitigate(doc):
    if not isinstance(doc, dict):
        raise Refused("the input is not a JSON object")
    counts = doc.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise Refused("`counts` must be a non-empty object of outcome: count")
    n = len(next(iter(counts)))
    if n < 1 or n > 16:
        raise Refused("the outcomes must be 1 to 16 bits wide")
    dist = [0.0] * (1 << n)
    shots = 0
    for key, k in counts.items():
        if len(key) != n or set(key) - {"0", "1"}:
            raise Refused("an outcome is not a string of 0 and 1 of the same width as the others")
        if not isinstance(k, int) or isinstance(k, bool) or k < 0:
            raise Refused("a count is not a non-negative integer")
        dist[int(key, 2)] += float(k)
        shots += k
    if shots == 0:
        raise Refused("the counts add up to 0")
    dist = [x / float(shots) for x in dist]
    readout = doc.get("readout")
    if readout is not None:
        per = readout.get("per_qubit") if isinstance(readout, dict) else None
        if not isinstance(per, dict):
            raise Refused("`readout` needs a `per_qubit` object")
        for qs, pair in per.items():
            if not qs.isdigit() or len(qs) > 6 or int(qs) >= n:
                raise Refused("a read-out qubit is not a number below the width of the outcomes")
            if not isinstance(pair, list) or len(pair) != 2:
                raise Refused("a read-out entry must be [p01, p10]")
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in pair):
                raise Refused("a read-out probability is not a number")
            e0, e1 = float(pair[0]), float(pair[1])
            if not (0.0 <= e0 <= 1.0 and 0.0 <= e1 <= 1.0):
                raise Refused("a read-out probability is outside [0, 1]")
            det = 1.0 - e0 - e1
            if not det > 0.0:
                raise Refused("a qubit's read-out errors add up to 1 or more, so they cannot be undone")
            bit = 1 << int(qs)
            for i in range(1 << n):
                if not i & bit:
                    a, b = dist[i], dist[i | bit]
                    dist[i] = ((1.0 - e1) * a - e1 * b) / det
                    dist[i | bit] = (0.0 - e0 * a + (1.0 - e0) * b) / det
    clipped = 0.0
    total = 0.0
    for i, x in enumerate(dist):
        if x < 0.0:
            clipped -= x
            dist[i] = 0.0
        total += dist[i]
    if not total > 0.0:
        raise Refused("the correction left no positive probability")
    return {"shots": shots, "clipped": clipped,
            "probabilities": {format(i, f"0{n}b"): x / total for i, x in enumerate(dist) if x > 0.0}}


def main():
    try:
        doc = json.loads(sys.stdin.read())
        print(json.dumps(mitigate(doc)))
    except (Refused, ValueError) as e:
        sys.stderr.write(f"qmitigate: {e}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
