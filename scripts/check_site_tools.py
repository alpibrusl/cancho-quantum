#!/usr/bin/env python3
"""Differential test of the cancho site libraries (tools/site/) against Python.

    CANCHO=path/to/cancho python3 scripts/check_site_tools.py

Number formatting (`numfmt.cho`) must give exactly what Python's `format`, `str` and `round` give, over
tens of thousands of doubles: random magnitudes from 1e-20 to 1e15, whole numbers, exact ties
(k + 1/2 over a power of ten, and binary fractions like 0.125), values a hair either side of a tie, and
results of ordinary arithmetic.
"""
import os
import random
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def build(compiler, files, out):
    r = subprocess.run([compiler, "build", *[os.path.join(ROOT, f) for f in files], "--std", "-o", out], capture_output=True, text=True)
    if r.returncode:
        sys.exit("build failed:\n" + r.stderr[-800:])


def numbers(rnd):
    xs = [0.0, 0.5, 1.5, 2.5, 0.125, 0.375, 1e-5, 2.5e-05, 0.0001, 9.5, 99.5, 0.05, 0.15, 0.25, 0.35, 1.005, 2.675, 1 / 3, 2 / 3, 0.1 + 0.2,
          123456.5, 999999.5, 1e15, 4503599627370496.0, 5e-324, 1e-20, 0.999999, 0.9999995, 9.9999995, 61.05, 3.14159265358979]
    for _ in range(6000):
        k = rnd.random()
        if k < 0.35:
            x = rnd.random() * 10 ** rnd.randint(-20, 15)
        elif k < 0.5:
            x = float(rnd.randint(0, 10 ** rnd.randint(1, 15)))
        elif k < 0.7:
            nd = rnd.randint(0, 6)
            x = (rnd.randint(0, 10 ** rnd.randint(1, 6)) + 0.5) / 10 ** nd      # a tie in decimal
        elif k < 0.8:
            nd = rnd.randint(0, 6)
            x = (rnd.randint(0, 10 ** rnd.randint(1, 6)) + 0.5) / 10 ** nd
            x = x * (1 + rnd.choice([-1, 1]) * 2.0 ** -rnd.randint(50, 53))          # a hair either side
        else:
            x = rnd.choice([0.1, 0.7, 1 / 7, 22 / 7]) * rnd.randint(1, 10 ** 6) / rnd.choice([1, 3, 7, 1000])
        xs.append(x)
    return xs


def check_svg(compiler):
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import site_svg
    exe = os.path.join(tempfile.mkdtemp(prefix="svgtest-"), "svgtest")
    build(compiler, ["tools/site/numfmt.cho", "tools/site/text.cho", "tools/site/svg.cho", "tools/site/svgtest.cho"], exe)
    cases, want = [], []
    diff = os.path.join(ROOT, "tests", "diff")
    labels = ["Circuit diagram: H on qubit 0", 'a "quoted" <label> & \'more\'', ""]
    for f in sorted(os.listdir(diff)):
        if not f.endswith(".qc"):
            continue
        lines = [l.split() for l in open(os.path.join(diff, f)) if l.strip()]
        if lines[0][0] != "n":
            continue
        n = int(lines[0][1])
        if n > 10:
            continue
        ops = [tuple([l[0]] + [int(x) for x in l[1:]]) for l in lines[1:]]
        ops = [o for o in ops if o[0] not in ("sample", "quiet") and o[0] in ("h", "x", "y", "z", "s", "t", "sdg", "tdg", "rx", "ry", "rz", "p", "cx", "cz", "cp", "swap", "ccx", "m", "seed", "trig")]
        for k, (current, natural) in enumerate(((None, False), (True, True), (True, False))):
            label = labels[k]
            cases.append(json.dumps({"fn": "circuit", "n": n, "ops": "".join(" ".join(map(str, o)) + "\n" for o in ops).rstrip("\n"), "label": label,
                                     "current": current is not None, "natural": natural}))
            want.append(site_svg.circuit_svg(n, ops, label, current=current, natural=natural))
    got = subprocess.run([exe], input="\n".join(cases) + "\n", capture_output=True, text=True).stdout.split("\n")[:-1]
    bad = [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    if len(got) != len(want):
        print(f"FAIL {len(got)} answers for {len(want)} circuits")
        return 1
    for i, g, w in bad[:2]:
        k = next(j for j in range(min(len(g), len(w))) if g[j] != w[j]) if g[: len(w)] != w[: len(g)] else min(len(g), len(w))
        print(f"FAIL case {i}: first difference at {k}: got {g[max(0, k - 60):k + 60]!r} want {w[max(0, k - 60):k + 60]!r}")
    print(f"{'FAIL' if bad else 'ok  '} svg.circuit vs site_svg.circuit_svg: {len(cases)} circuit diagrams, {len(bad)} differences")
    return 1 if bad else 0


def main():
    compiler = os.environ.get("CANCHO", "cancho")
    failed = check_svg(compiler)
    exe = os.path.join(tempfile.mkdtemp(prefix="numtest-"), "numtest")
    build(compiler, ["tools/site/numfmt.cho", "tools/site/numtest.cho"], exe)
    rnd = random.Random(20241024)
    lines, want = [], []
    for x in numbers(rnd):
        j = repr(float(x))
        if j.startswith("-") or "inf" in j or "nan" in j:
            continue
        for nd in range(0, 7):
            lines.append(f"fixed {nd} {j}")
            want.append(format(x, f".{nd}f"))
        for nd in range(0, 4):
            lines.append(f"sci {nd} {j}")
            want.append(format(x, f".{nd}e"))
        lines.append(f"general {j}")
        want.append(format(x, "g"))
        lines.append(f"repr {j}")
        want.append(str(x))
        if x < 1e9:
            for nd in (1, 4, 6):
                lines.append(f"round {nd} {j}")
                want.append(str(round(x, nd)))
        # a negative of the same, once in a while
        if rnd.random() < 0.05:
            lines.append(f"fixed 3 -{j}")
            want.append(format(-x, ".3f"))
    got = subprocess.run([exe], input="\n".join(lines) + "\n", capture_output=True, text=True).stdout.split("\n")[:-1]
    if len(got) != len(want):
        sys.exit(f"FAIL {len(got)} answers for {len(want)} questions")
    bad = [(l, g, w) for l, g, w in zip(lines, got, want) if g != w]
    for l, g, w in bad[:10]:
        print(f"FAIL {l!r}: got {g!r}, Python gives {w!r}")
    print(f"{'FAIL' if bad else 'ok  '} numfmt vs Python: {len(lines)} formatted numbers, {len(bad)} differences")
    sys.exit(1 if bad or failed else 0)


if __name__ == "__main__":
    main()
