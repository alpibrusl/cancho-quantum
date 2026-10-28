#!/usr/bin/env python3
"""The sampled QAOA of examples/qaoa: what SPSA and Nelder-Mead find from shots. Prints the table of that README.

    CANCHO=... OPT=... python3 scripts/qaoa_study.py [--layers 2] [--seeds 5]

For each setting `qaoa --shots S` is run with seeds 1 to N (6 starts each); `ratio` is the exact expected cut at the angles found over the best cut (7), not what the optimiser saw.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CANCHO = os.environ.get("CANCHO", "cancho")
OPT = os.environ["OPT"]


def build(name, main):
    exe = os.path.join(tempfile.mkdtemp(prefix="qaoa-"), name)
    files = [os.path.join(ROOT, f) for f in ("src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho", "examples/qaoa/model.cho", main)]
    r = subprocess.run([CANCHO, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])
    return exe


def main():
    layers = sys.argv[sys.argv.index("--layers") + 1] if "--layers" in sys.argv else "2"
    seeds = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 5
    energy, gradient, sampled, driver = (build(n, f) for n, f in (("qaoa-energy", "examples/qaoa/energy.cho"), ("qaoa-gradient", "examples/qaoa/gradient.cho"), ("qaoa-sampled", "examples/qaoa/sampled.cho"), ("qaoa", "examples/qaoa/qaoa.cho")))
    r = subprocess.run([driver, "--layers", layers, "--opt", OPT, "--energy", energy, "--gradient", gradient], capture_output=True, text=True)
    exact = json.loads(r.stdout)
    print(f"exact energy, BFGS with the parameter-shift gradient, {layers} layers: expected cut {exact['expected_cut']:.4f}, ratio {exact['ratio']:.4f}, {exact['gradients']} gradients\n")
    print("| method | shots per evaluation | readout | median ratio | worst ratio | median shots spent |")
    print("|---|---|---|---|---|---|")
    for method, extra in (("spsa", ["--maxiter", "200"]), ("nelder-mead", ["--maxfev", "2000"])):
        for S, ro in ((100, 0.0), (1000, 0.0), (1000, 0.05)):
            res = []
            for seed in range(1, seeds + 1):
                args = [driver, "--method", method, "--layers", layers, "--opt", OPT, "--energy", energy, "--sampled", sampled, "--shots", str(S), "--seed", str(seed), *extra]
                if ro:
                    args += ["--readout", str(ro)]
                out = subprocess.run(args, capture_output=True, text=True)
                if out.returncode:
                    sys.exit(f"qaoa failed: {out.stderr[-300:]}")
                res.append(json.loads(out.stdout))
            print(f"| {method} | {S} | {ro} | {statistics.median(x['ratio'] for x in res):.4f} | {min(x['ratio'] for x in res):.4f} | {statistics.median(x['shots'] for x in res):,.0f} |")


main()
