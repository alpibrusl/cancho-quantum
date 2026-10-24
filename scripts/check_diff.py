#!/usr/bin/env python3
"""Run every circuit in tests/diff/ through qsim and compare with its .ref.

    python3 scripts/check_diff.py [--tol 1e-12] [--backend cranelift|llvm] [name ...]

Builds `qsim` once with the compiler on PATH (or $CANCHO), runs each `.qc`
on standard input, and compares:

  * amplitudes: every real and imaginary part within `--tol` of the
    reference (absolute); a missing index is 0 on either side;
  * measurement bits and their order, and `sample` counts: exactly;
  * `trig` lines: reported as ulp distance from the C library, not gated
    (std.math is fdlibm ported to cancho, not libm; see float-math.md §8).

Exits 0 only if every gated comparison passes. Prints the worst error seen
per circuit and overall, which is the number the M1 gate asks for.
"""
import argparse
import json
import math
import os
import struct
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIFF = os.path.join(ROOT, "tests", "diff")


def ulps(a, b):
    """Distance in representable doubles between two finite floats."""
    def key(x):
        (i,) = struct.unpack("<q", struct.pack("<d", x))
        return i if i >= 0 else -(1 << 63) - i
    return abs(key(a) - key(b))


def parse(text, n_amp=None):
    ms, trig, amp, smp, rho, scal = [], [], {}, [], {}, []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if f[0] == "m":
            ms.append((int(f[1]), int(f[2])))
        elif f[0] == "trig":
            trig.append((float(f[1]), float(f[2])))
        elif f[0] == "sample":
            smp.append((f[1], int(f[2])))
        elif f[0] == "rho":
            rho[(int(f[1]), int(f[2]))] = (float(f[3]), float(f[4]))
        elif f[0] in ("purity", "trace"):
            scal.append((f[0], float(f[1])))
        elif f[0] == "prob":
            scal.append(("prob", f[1], float(f[2])))
        elif f[0] == "amp":
            amp[int(f[1])] = (float(f[2]), float(f[3]))
    return ms, trig, amp, smp, rho, scal


def build(compiler, backend, exe):
    srcs = [os.path.join(ROOT, "src", f) for f in sorted(os.listdir(os.path.join(ROOT, "src"))) if f.endswith(".cho")]
    cmd = [compiler, "build", *srcs, "--std", "--backend", backend, "-o", exe]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=1e-12)
    ap.add_argument("--backend", default="cranelift")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    ap.add_argument("--exe", default=None, help="use an already-built qsim")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()

    exe = args.exe or os.path.join("/tmp", f"qsim-{args.backend}")
    if not args.exe:
        build(args.compiler, args.backend, exe)

    names = args.names or sorted(f[:-3] for f in os.listdir(DIFF) if f.endswith(".qc"))
    worst_all, failed, trig_worst = 0.0, [], 0
    rows = []
    for name in names:
        with open(os.path.join(DIFF, name + ".qc")) as f:
            circuit = f.read()
        with open(os.path.join(DIFF, name + ".ref")) as f:
            want = parse(f.read())
        t0 = time.time()
        run = subprocess.run([exe], input=circuit, capture_output=True, text=True)
        dt = time.time() - t0
        if run.returncode != 0:
            print(f"FAIL {name}: exit {run.returncode}")
            failed.append(name)
            continue
        got = parse(run.stdout)
        ok = True
        if got[0] != want[0]:
            print(f"FAIL {name}: measurements {got[0]} != {want[0]}")
            ok = False
        if got[3] != want[3]:
            print(f"FAIL {name}: sample counts {got[3]} != {want[3]}")
            ok = False
        worst = 0.0
        if len(got[5]) != len(want[5]) or any(g[:-1] != w[:-1] for g, w in zip(got[5], want[5])):
            print(f"FAIL {name}: scalar lines {got[5]} != {want[5]}")
            ok = False
        else:
            for g, w in zip(got[5], want[5]):
                worst = max(worst, abs(g[-1] - w[-1]))
        for key in set(got[4]) | set(want[4]):
            g, w = got[4].get(key, (0.0, 0.0)), want[4].get(key, (0.0, 0.0))
            worst = max(worst, abs(g[0] - w[0]), abs(g[1] - w[1]))
        for i in set(got[2]) | set(want[2]):
            g = got[2].get(i, (0.0, 0.0))
            w = want[2].get(i, (0.0, 0.0))
            worst = max(worst, abs(g[0] - w[0]), abs(g[1] - w[1]))
        if worst > args.tol:
            ok = False
            print(f"FAIL {name}: worst amplitude error {worst:.3e} > {args.tol:g}")
        # trig is compared to libm in ulps, and reported rather than gated.
        tw = 0
        if len(got[1]) == len(want[1]):
            for g, w in zip(got[1], want[1]):
                tw = max(tw, ulps(g[0], w[0]), ulps(g[1], w[1]))
        else:
            ok = False
            print(f"FAIL {name}: {len(got[1])} trig lines, wanted {len(want[1])}")
        trig_worst = max(trig_worst, tw)
        worst_all = max(worst_all, worst)
        if ok:
            extra = f"  trig {tw} ulp" if want[1] else ""
            print(f"ok   {name:18s} worst {worst:.2e}  {dt:5.2f}s{extra}")
            rows.append([name, f"{worst:.2e}"])
        else:
            failed.append(name)
    # Programs that must stop. A trap is the run-time half of the must-reject
    # list (docs/qubit-types.md section 4.2): exit non-zero, and no amplitudes.
    trapdir = os.path.join(ROOT, "tests", "trap")
    for f in sorted(os.listdir(trapdir)) if not args.names else []:
        run = subprocess.run([exe], input=open(os.path.join(trapdir, f)).read(), capture_output=True, text=True)
        if run.returncode != 0 and "amp " not in run.stdout:
            print(f"ok   trap {f[:-3]:22s} exit {run.returncode}")
        else:
            print(f"FAIL trap {f[:-3]}: exit {run.returncode}, {len(run.stdout)} bytes out")
            failed.append(f)
    print(f"\nworst amplitude error over {len(names)} circuits: {worst_all:.3e} (gate {args.tol:g})")
    if not args.names and not failed:
        # What the landing page reports (docs/data/check_diff.json); the builders read it and do not re-run this.
        with open(os.path.join(ROOT, "docs", "data", "check_diff.json"), "w") as f:
            json.dump({"circuits": len(names), "worst": f"{worst_all:.3e}", "trig_ulp": trig_worst, "rows": rows}, f, indent=1)
            f.write("\n")
    print(f"worst sin/cos distance from libm over the `trig` lines: {trig_worst} ulp")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
