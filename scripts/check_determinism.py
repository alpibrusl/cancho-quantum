#!/usr/bin/env python3
"""The M3 gate: same circuit + same seed gives byte-identical output.

    python3 scripts/check_determinism.py [--arm64] [--update] [--compiler cancho]

For every circuit in tests/diff/ this runs the circuit four ways, each
from a separate build:

    interpreted (qsim, circuit on stdin)   x  Cranelift, LLVM
    compiled    (tests/circuits/<name>.cho) x  Cranelift, LLVM

and with `--arm64` two more (LLVM, interpreted and compiled), built for
aarch64-unknown-linux-gnu and run under qemu-user. All outputs for one
circuit must be byte-identical, and their SHA-256 must match
tests/golden/outputs.sha256 (`--update` rewrites it).

It also writes tests/golden/provenance.json, tying each run to the code
that produced it: the circuit's content identity from `cancho ids`
(`body circuit`), a digest of every library function's body identity, the
input's hash, and the output's hash. Two machines that agree on this file
ran the same code on the same circuit and got the same bytes.

--arm64 needs `qemu-aarch64`, `aarch64-linux-gnu-gcc` and its sysroot
(Debian/Ubuntu: qemu-user gcc-aarch64-linux-gnu libc6-dev-arm64-cross).
It is emulation: it checks the compiled aarch64 code, not arm64 hardware.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "src")
LIB = [os.path.join(SRC, f) for f in ("complex.cho", "state.cho", "gates.cho", "measure.cho", "noise.cho", "dump.cho")]
GOLD = os.path.join(ROOT, "tests", "golden")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build(compiler, files, exe, backend, arm, shim):
    cmd = [compiler, "build", *files, "--std", "--backend", backend, "-o", exe]
    env = dict(os.environ)
    if arm:
        cmd += ["--target", "aarch64-unknown-linux-gnu"]
        env["PATH"] = shim + os.pathsep + env["PATH"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"build failed: {' '.join(cmd)}\n{r.stderr[-600:]}")


def run(exe, data, arm):
    cmd = ["qemu-aarch64", "-L", "/usr/aarch64-linux-gnu", exe] if arm else [exe]
    r = subprocess.run(cmd, input=data, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} exited {r.returncode}")
    return r.stdout


def ids(compiler, files):
    r = subprocess.run([compiler, "ids", *files, "--std"], capture_output=True, text=True, check=True)
    out = {}
    for line in r.stdout.splitlines():
        f = line.split()
        if len(f) == 3 and f[0] in ("sig", "body", "type"):
            out[(f[0], f[1])] = f[2]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    ap.add_argument("--arm64", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()

    names = args.names or sorted(f[:-3] for f in os.listdir(os.path.join(ROOT, "tests", "diff")) if f.endswith(".qc"))
    tmp = tempfile.mkdtemp(prefix="m3-")
    shim = os.path.join(tmp, "shim")
    os.makedirs(shim)
    if args.arm64:
        os.symlink(shutil.which("aarch64-linux-gnu-gcc"), os.path.join(shim, "cc"))

    configs = [("interp", b, False) for b in ("cranelift", "llvm")] + [("compiled", b, False) for b in ("cranelift", "llvm")]
    if args.arm64:
        configs += [("interp", "llvm", True), ("compiled", "llvm", True)]

    def label(kind, backend, arm):
        return f"{kind}-{backend}" + ("-arm64" if arm else "")

    # Build the interpreter once per configuration, and each compiled circuit.
    jobs = {}
    with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for kind, backend, arm in configs:
            if kind == "interp":
                exe = os.path.join(tmp, label(kind, backend, arm))
                files = [os.path.join(SRC, f) for f in sorted(os.listdir(SRC)) if f.endswith(".cho")]
                jobs[(kind, backend, arm, None)] = (exe, pool.submit(build, args.compiler, files, exe, backend, arm, shim))
            else:
                for n in names:
                    exe = os.path.join(tmp, f"{label(kind, backend, arm)}-{n}")
                    files = LIB + [os.path.join(ROOT, "tests", "circuits", n + ".cho")]
                    jobs[(kind, backend, arm, n)] = (exe, pool.submit(build, args.compiler, files, exe, backend, arm, shim))
        for key, (exe, fut) in jobs.items():
            fut.result()

    golden_path = os.path.join(GOLD, "outputs.sha256")
    golden = {}
    if os.path.exists(golden_path):
        for line in open(golden_path):
            h, _, n = line.strip().partition("  ")
            golden[n] = h

    lib_ids = ids(args.compiler, LIB)
    lib_digest = sha("\n".join(f"{k[1]} {v}" for k, v in sorted(lib_ids.items()) if k[0] == "body").encode())
    prov, failed, new_golden = {}, [], {}
    for n in names:
        data = open(os.path.join(ROOT, "tests", "diff", n + ".qc"), "rb").read()
        outs = {}
        for kind, backend, arm in configs:
            exe = jobs[(kind, backend, arm, None if kind == "interp" else n)][0]
            outs[label(kind, backend, arm)] = run(exe, data, arm)
        hashes = {sha(o) for o in outs.values()}
        circ = ids(args.compiler, LIB + [os.path.join(ROOT, "tests", "circuits", n + ".cho")])
        # `ids` over the same file twice must agree.
        again = ids(args.compiler, LIB + [os.path.join(ROOT, "tests", "circuits", n + ".cho")])
        stable = circ == again
        h = next(iter(hashes))
        new_golden[n] = h
        ok = len(hashes) == 1 and stable and (args.update or golden.get(n) == h)
        prov[n] = {
            "circuit_body_id": circ[("body", "circuit")],
            "library_digest": lib_digest,
            "input_sha256": sha(data),
            "output_sha256": h,
        }
        if ok:
            print(f"ok   {n:18s} {h[:16]}  {len(outs)} builds identical")
        else:
            why = "builds differ: " + ", ".join(f"{k}={sha(v)[:8]}" for k, v in outs.items()) if len(hashes) != 1 else \
                  ("ids unstable" if not stable else f"golden {golden.get(n, 'missing')[:16]} != {h[:16]}")
            print(f"FAIL {n}: {why}")
            failed.append(n)
    if args.update and not args.names:
        os.makedirs(GOLD, exist_ok=True)
        with open(golden_path, "w") as f:
            for n in sorted(new_golden):
                f.write(f"{new_golden[n]}  {n}\n")
        with open(os.path.join(GOLD, "provenance.json"), "w") as f:
            json.dump(prov, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {golden_path} and provenance.json")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(names) - len(failed)} of {len(names)} circuits: {len(configs)} builds each"
          + (" (incl. arm64 under qemu)" if args.arm64 else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
