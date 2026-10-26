#!/usr/bin/env python3
"""`tools/qmitigate.cho` against its reference `scripts/mitigate.py`, and against the physics.

    CANCHO=path/to/cancho python3 scripts/check_mitigate.py

1. a hand-worked case: one qubit with p01 = 0.1, p10 = 0.2 reading the state 0.7/0.3 gives 0.69/0.31, and undoing it returns 0.7/0.3;
2. random inputs (1 to 6 qubits, random counts, random per-qubit errors, some qubits without an entry): the tool and the reference
   print the same distribution, to 1e-12;
3. broken inputs: both refuse (the tool exits 2 with `qmitigate: ...`, the reference raises);
4. the point of it: counts made by pushing a known distribution through known read-out errors (exact, as integers of 10^9 shots)
   are returned to that distribution, to 1e-6 (the rounding of the counts).
"""
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mitigate  # noqa: E402
import tools_lib  # noqa: E402


def cho(doc):
    r = subprocess.run([tools_lib.tool("qmitigate")], input=doc if isinstance(doc, str) else json.dumps(doc), capture_output=True, text=True)
    return r


def close(a, b, tol):
    return a["shots"] == b["shots"] and abs(a["clipped"] - b["clipped"]) <= tol and a["probabilities"].keys() == b["probabilities"].keys() and \
        all(abs(a["probabilities"][k] - b["probabilities"][k]) <= tol for k in a["probabilities"])


def main():
    failed = 0

    # 1
    r = cho({"readout": {"per_qubit": {"0": [0.1, 0.2]}}, "counts": {"0": 690000, "1": 310000}})
    got = json.loads(r.stdout)["probabilities"]
    ok = r.returncode == 0 and abs(got["0"] - 0.7) < 1e-12 and abs(got["1"] - 0.3) < 1e-12
    print(f"{'ok  ' if ok else 'FAIL'} hand-worked case: 0.69/0.31 -> {got}")
    failed += not ok

    # 2
    rnd = random.Random(5)
    bad = 0
    for _ in range(400):
        n = rnd.randint(1, 6)
        counts = {format(i, f"0{n}b"): rnd.randint(0, 500) for i in range(1 << n) if rnd.random() < 0.7}
        if sum(counts.values()) == 0:
            counts["0" * n] = 1
        per = {str(q): [round(rnd.uniform(0, 0.2), 4), round(rnd.uniform(0, 0.3), 4)] for q in range(n) if rnd.random() < 0.8}
        doc = {"readout": {"per_qubit": per}, "counts": counts}
        a, b = cho(doc), mitigate.mitigate(doc)
        if a.returncode != 0 or not close(json.loads(a.stdout), b, 1e-12):
            bad += 1
    print(f"{'ok  ' if not bad else 'FAIL'} 400 random inputs: the tool and scripts/mitigate.py agree to 1e-12 ({bad} differences)")
    failed += bool(bad)

    # 3
    broken = [
        "not json", "[]", {}, {"counts": {}}, {"counts": {"0": 1, "11": 1}}, {"counts": {"2": 1}}, {"counts": {"0": -1}}, {"counts": {"0": 1.5}},
        {"counts": {"0": 0}}, {"counts": {"0": 1}, "readout": {"per_qubit": {"1": [0.1, 0.1]}}}, {"counts": {"0": 1}, "readout": {"per_qubit": {"0": [0.5, 0.5]}}},
        {"counts": {"0": 1}, "readout": {"per_qubit": {"0": [0.7, 0.4]}}}, {"counts": {"0": 1}, "readout": {"per_qubit": {"0": [-0.1, 0.1]}}},
        {"counts": {"0": 1}, "readout": {"per_qubit": {"0": [0.1]}}}, {"counts": {"0": 1}, "readout": {"per_qubit": {"x": [0.1, 0.1]}}},
        {"counts": {"0": 1}, "readout": {"per_qubit": {"0": ["a", 0.1]}}}, {"counts": {"0": 1}, "readout": {}}, {"counts": {"0" * 17: 1}},
    ]
    nothing = 0
    for doc in broken:
        r = cho(doc)
        try:
            mitigate.mitigate(json.loads(doc) if isinstance(doc, str) else doc)
            ref_refused = False
        except (mitigate.Refused, ValueError):
            ref_refused = True
        if not (r.returncode == 2 and r.stdout == "" and r.stderr.startswith("qmitigate: ") and ref_refused):
            nothing += 1
            print("   not refused by both:", str(doc)[:80], r.returncode, r.stderr.strip())
    print(f"{'ok  ' if not nothing else 'FAIL'} {len(broken)} broken inputs: both refuse, the tool with `qmitigate: ...` on standard error and nothing on standard output")
    failed += bool(nothing)

    # 4
    worst = 0.0
    for _ in range(40):
        n = rnd.randint(1, 5)
        true = [rnd.random() ** 3 for _ in range(1 << n)]
        s = sum(true)
        true = [x / s for x in true]
        err = [(rnd.uniform(0.0, 0.1), rnd.uniform(0.0, 0.15)) for _ in range(n)]
        dist = list(true)
        for q, (e0, e1) in enumerate(err):          # push the true distribution through the confusion matrices
            bit = 1 << q
            for i in range(1 << n):
                if not i & bit:
                    a, b = dist[i], dist[i | bit]
                    dist[i], dist[i | bit] = (1 - e0) * a + e1 * b, e0 * a + (1 - e1) * b
        shots = 10 ** 9
        counts = {format(i, f"0{n}b"): round(p * shots) for i, p in enumerate(dist)}
        doc = {"readout": {"per_qubit": {str(q): [e0, e1] for q, (e0, e1) in enumerate(err)}}, "counts": counts}
        got = json.loads(cho(doc).stdout)["probabilities"]
        for i, p in enumerate(true):
            worst = max(worst, abs(got.get(format(i, f"0{n}b"), 0.0) - p))
    ok = worst < 1e-6
    print(f"{'ok  ' if ok else 'FAIL'} known distributions through known read-out errors come back: worst difference {worst:.1e}")
    failed += not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
