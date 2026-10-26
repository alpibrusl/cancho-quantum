#!/usr/bin/env python3
"""`tools/qscan.cho` against its reference `scripts/scan_ops.py`, and in `qsim`.

    CANCHO=path/to/cancho python3 scripts/check_scan.py

1. 500 random scans (random qubits, probabilities, with and without a `qubits` line): the tool and the reference print the same bytes;
2. broken inputs: both refuse (the tool exits 2 with `qscan: ...` and prints nothing on standard output);
3. in `qsim`: the lines the tool prints are accepted, and a qubit with `readerr` p01 = 0.2 that is measured idle reads 1 about a fifth of the time
   (4000 shots, within four standard deviations), where one without reads 0 every time.
"""
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_ops  # noqa: E402
import tools_lib  # noqa: E402


def cho(text):
    return subprocess.run([tools_lib.tool("qscan")], input=text, capture_output=True, text=True)


def main():
    failed = 0
    rnd = random.Random(11)
    bad = 0
    for _ in range(500):
        qubits = rnd.sample(range(0, 156), rnd.randint(1, 8))
        scan = {"qubits": {str(q): {"idle_reads_1": rnd.choice([0, 1, round(rnd.random(), rnd.randint(1, 9)), rnd.random() / 50]),
                                    "after_x_reads_0": rnd.choice([0, 1, round(rnd.random(), rnd.randint(1, 9)), rnd.random() / 50])} for q in qubits}}
        text = json.dumps(scan, indent=rnd.choice([None, 1]))
        if rnd.random() < 0.7:
            order = rnd.sample(qubits, len(qubits))
            text = "qubits " + " ".join(map(str, order)) + "\n" + text
        else:
            text = json.dumps({"qubits": {str(q % 20): v for q, v in zip(qubits, scan["qubits"].values())}})
        r = cho(text)
        want = scan_ops.ops(text)
        if r.returncode != 0 or r.stdout != want:
            bad += 1
            if bad < 3:
                print("  differs:", text[:120].replace("\n", "|"), "\n    tool:", r.stdout[:80], "\n    ref: ", want[:80])
    print(f"{'ok  ' if not bad else 'FAIL'} 500 random scans: the tool and scripts/scan_ops.py print the same bytes ({bad} differences)")
    failed += bool(bad)

    broken = ["", "not json", "[]", "{}", '{"qubits": []}', '{"qubits": {"0": 1}}', '{"qubits": {"0": {"idle_reads_1": 0.1}}}',
              '{"qubits": {"0": {"idle_reads_1": 1.5, "after_x_reads_0": 0}}}', '{"qubits": {"0": {"idle_reads_1": -0.1, "after_x_reads_0": 0}}}',
              '{"qubits": {"0": {"idle_reads_1": "a", "after_x_reads_0": 0}}}', 'qubits 5\n{"qubits": {"0": {"idle_reads_1": 0, "after_x_reads_0": 0}}}',
              'qubits x\n{}', "qubits " + " ".join(str(i) for i in range(21)) + "\n{}"]
    nothing = 0
    for text in broken:
        r = cho(text)
        try:
            scan_ops.ops(text)
            ref = False
        except scan_ops.Refused:
            ref = True
        if not (r.returncode == 2 and r.stdout == "" and r.stderr.startswith("qscan: ") and ref):
            nothing += 1
            print("   not refused by both:", text[:60].replace("\n", "|"), r.returncode, r.stderr.strip())
    print(f"{'ok  ' if not nothing else 'FAIL'} {len(broken)} broken inputs: both refuse, the tool with `qscan: ...` on standard error and nothing on standard output")
    failed += bool(nothing)

    # 3
    exe = os.environ.get("QSIM")
    if exe is None:
        exe = os.path.join(os.path.dirname(tools_lib.tool("qscan")), "qsim")
        files = [os.path.join(tools_lib.ROOT, "src", f) for f in sorted(os.listdir(os.path.join(tools_lib.ROOT, "src"))) if f.endswith(".cho")]
        b = subprocess.run([os.environ.get("CANCHO", "cancho"), "build", *files, "--std", "-o", exe], capture_output=True, text=True)
        if b.returncode:
            sys.exit("cannot build qsim:\n" + b.stderr[-600:])
    scan = {"qubits": {"7": {"idle_reads_1": 0.2, "after_x_reads_0": 0.0}, "9": {"idle_reads_1": 0.0, "after_x_reads_0": 0.0}}}
    ops = cho("qubits 7 9\n" + json.dumps(scan)).stdout
    sampled = subprocess.run([exe], input="n 2\nseed 3\n" + ops + "".join("m 0\nm 1\n" for _ in range(4000)), capture_output=True, text=True)
    meas = [l.split() for l in sampled.stdout.splitlines() if l.startswith("m")]
    ones0 = sum(1 for l in meas if l[1] == "0" and l[-1] == "1")
    ones1 = sum(1 for l in meas if l[1] == "1" and l[-1] == "1")
    sd = (4000 * 0.2 * 0.8) ** 0.5
    ok = sampled.returncode == 0 and abs(ones0 - 800) <= 4 * sd and ones1 == 0
    print(f"{'ok  ' if ok else 'FAIL'} in qsim: qubit 0 (device qubit 7, p01 0.2) read 1 in {ones0} of 4000 idle shots (expected 800 +- {4 * sd:.0f}), qubit 1 (p01 0) in {ones1}")
    failed += not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
