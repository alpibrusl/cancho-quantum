#!/usr/bin/env python3
"""The M2 gate: the typed qubit layer's accept and reject fixtures.

    python3 scripts/check_types.py [--compiler cancho] [--backend cranelift]

Fixtures carry their expectation in `//~` comments, the format the
compiler repository uses:

  tests/reject/*.cho   `//~ RULE <tag>`  one line per rule the checker must
                       report, and no others. Checked with
                       `cancho check --output json`.
  tests/accept/*.cho   must compile and run. `//~ STDOUT <line>` lines must
                       match the output in order; `//~ EXIT <n>` (default 0);
                       `//~ TRAPS` means it must compile and then stop with
                       a non-zero status (a run-time trap).

Every fixture is checked together with the library modules in `src/`
(everything except `main.cho`, which is the `qsim` driver).
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def library():
    d = os.path.join(ROOT, "src")
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".cho") and f != "main.cho"]


def expectations(path):
    exp = {"rules": [], "stdout": [], "exit": 0, "traps": False}
    for line in open(path):
        if not line.startswith("//~"):
            continue
        body = line[3:].strip()
        key, _, val = body.partition(" ")
        if key == "RULE":
            exp["rules"].append(val.strip())
        elif key == "STDOUT":
            exp["stdout"].append(val)
        elif key == "EXIT":
            exp["exit"] = int(val)
        elif key == "TRAPS":
            exp["traps"] = True
    return exp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    ap.add_argument("--backend", default="cranelift")
    ap.add_argument("names", nargs="*", help="fixture file names (without directory)")
    args = ap.parse_args()
    lib = library()
    failed, count = [], 0

    rdir = os.path.join(ROOT, "tests", "reject")
    for f in sorted(os.listdir(rdir)):
        if not f.endswith(".cho") or (args.names and f not in args.names):
            continue
        count += 1
        path = os.path.join(rdir, f)
        exp = expectations(path)
        run = subprocess.run([args.compiler, "check", *lib, path, "--std", "--output", "json"],
                             capture_output=True, text=True)
        try:
            got = sorted({r["rule"] for r in json.loads(run.stdout).get("refused", [])})
        except (ValueError, AttributeError):
            got = [f"unparsable: {run.stdout[:80]!r}"]
        want = sorted(set(exp["rules"]))
        if got == want and run.returncode != 0:
            print(f"ok   reject {f[:-4]:28s} {', '.join(got)}")
        else:
            print(f"FAIL reject {f[:-4]}: wanted {want}, got {got}, exit {run.returncode}")
            failed.append(f)

    adir = os.path.join(ROOT, "tests", "accept")
    for f in sorted(os.listdir(adir)):
        if not f.endswith(".cho") or (args.names and f not in args.names):
            continue
        count += 1
        path = os.path.join(adir, f)
        exp = expectations(path)
        exe = os.path.join("/tmp", f"m2-{args.backend}-{f[:-4]}")
        build = subprocess.run([args.compiler, "build", *lib, path, "--std", "--backend", args.backend, "-o", exe],
                               capture_output=True, text=True)
        if build.returncode != 0:
            print(f"FAIL accept {f[:-4]}: does not compile\n{build.stderr[:400]}")
            failed.append(f)
            continue
        run = subprocess.run([exe], capture_output=True, text=True)
        out = run.stdout.splitlines()
        if exp["traps"]:
            ok = run.returncode != 0
            note = f"traps (exit {run.returncode})"
        else:
            ok = run.returncode == exp["exit"] and out == exp["stdout"]
            note = f"exit {run.returncode}"
        if ok:
            print(f"ok   accept {f[:-4]:28s} {note}")
        else:
            print(f"FAIL accept {f[:-4]}: exit {run.returncode}, stdout {out}, wanted {exp['stdout']}")
            failed.append(f)

    print(f"\n{count - len(failed)} of {count} fixtures behave as stated")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
