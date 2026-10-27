#!/usr/bin/env python3
"""The sampled VQE of examples/vqe (README.md, "Sampling"): what the optimisers find with shot noise and read-out error. Prints the table of that README.

    CANCHO=... OPT=... python3 scripts/vqe_noise_study.py [--layers 3] [--seeds 5]

For each setting, `vqe --shots S` is run with seeds 1 to N; `true_error` is the exact energy at the angles found minus the exact ground state energy (not what the optimiser saw, which noise makes optimistic: it can lie below the ground
state energy, and which a read-out error makes pessimistic unless mitigated; the column `reported - exact` shows both). Nelder-Mead runs one `opt` run of at most 4000 evaluations, BFGS one run with a gradient tolerance of 1e-6 (the noise usually stops it first: `converged` false is "precision loss").
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
    exe = os.path.join(tempfile.mkdtemp(prefix="vqe-"), name)
    files = [os.path.join(ROOT, f) for f in ("src/complex.cho", "src/gates.cho", "src/measure.cho", "src/profile.cho", "src/state.cho", "examples/vqe/model.cho", main)]
    r = subprocess.run([CANCHO, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr[-800:])
    return exe


def main():
    layers = sys.argv[sys.argv.index("--layers") + 1] if "--layers" in sys.argv else "3"
    seeds = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 5
    energy, gradient, sampled, driver = (build(n, f) for n, f in (("vqe-energy", "examples/vqe/energy.cho"), ("vqe-gradient", "examples/vqe/gradient.cho"), ("vqe-sampled", "examples/vqe/sampled.cho"), ("vqe", "examples/vqe/vqe.cho")))
    settings = [(S, 0.0, False) for S in (100, 1000, 4096)] + [(1000, 0.03, False), (1000, 0.03, True)]
    print(f"| method | shots per basis | read-out error | mitigated | median true error | worst true error | median (what the optimiser reported - exact) | median shots spent | converged |")
    print("|---|---|---|---|---|---|---|---|---|")
    for method in ("bfgs", "nelder-mead"):
        for S, ro, mit in settings:
            res = []
            for seed in range(1, seeds + 1):
                args = [driver, "--method", method, "--layers", layers, "--opt", OPT, "--energy", energy, "--gradient", gradient, "--sampled", sampled, "--shots", str(S), "--seed", str(seed), "--restarts", "1", "--maxfev", "4000"]
                if ro:
                    args += ["--readout", str(ro)]
                if mit:
                    args += ["--mitigate"]
                r = subprocess.run(args, capture_output=True, text=True)
                if r.returncode not in (0, 1):
                    sys.exit(f"vqe failed: {r.stderr[-300:]}")
                res.append(json.loads(r.stdout))
            errs = [x["true_error"] for x in res]
            print(f"| {method} | {S} | {ro} | {'yes' if mit else 'no'} | {statistics.median(errs):.3f} | {max(errs):.3f} | {statistics.median(x['error'] for x in res):+.3f} | {statistics.median(x['shots'] for x in res):,.0f} | {sum(x['converged'] for x in res)} of {seeds} |")


main()
