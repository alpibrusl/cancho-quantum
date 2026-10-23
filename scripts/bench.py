#!/usr/bin/env python3
"""Time `qsim` on H applied to every qubit, for 10 to 20 qubits, on both backends.

    CANCHO=path/to/cancho python3 scripts/bench.py

Writes docs/data/timings.json, which the landing page reads. Timings are not
reproducible bit for bit, so `build_site.py --check` does not run this: it
reads the file. The minimum of three runs is kept, output is suppressed
with `quiet` (printing a million amplitudes takes longer than computing them,
see docs/m1-results.md), and the machine is recorded.
"""
import json
import os
import platform
import subprocess
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    cancho = os.environ.get("CANCHO", "cancho")
    srcs = sorted(os.path.join(ROOT, "src", f) for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
    tmp = tempfile.mkdtemp(prefix="bench-")
    xs = list(range(10, 21))
    out = {"qubits": xs, "seconds": {}, "gates_per_run": "n (one H on each qubit)"}
    for backend in ("cranelift", "llvm"):
        exe = os.path.join(tmp, backend)
        subprocess.run([cancho, "build", *srcs, "--std", "--backend", backend, "-o", exe], check=True, capture_output=True)
        ts = []
        for n in xs:
            circuit = f"n {n}\n" + "".join(f"h {q}\n" for q in range(n)) + "quiet\n"
            best = min(_time(exe, circuit) for _ in range(3))
            ts.append(round(best, 4))
        out["seconds"][backend] = ts
    out["machine"] = f"{platform.machine()}, {os.cpu_count()} cores, {platform.system()} {platform.release()}"
    out["measured"] = time.strftime("%Y-%m-%d")
    os.makedirs(os.path.join(ROOT, "docs", "data"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "data", "timings.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out["seconds"]))


def _time(exe, circuit):
    t = time.perf_counter()
    subprocess.run([exe], input=circuit, capture_output=True, text=True, check=True)
    return time.perf_counter() - t


if __name__ == "__main__":
    main()
