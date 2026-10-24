#!/usr/bin/env python3
"""Differential test of the cancho tools against their Python reference implementations.

    CANCHO=path/to/cancho python3 scripts/check_tools.py

`tools/qprofile.cho` must print exactly what `scripts/noise_profile.py` prints, for the two
checked-in profiles, for 400 random valid profiles (random sizes, rates down to ties of the
rounding, per-qubit and per-pair entries in shuffled order, durations, coherence), and with a
circuit; and it must refuse, with nothing on standard output, every one of 200 random broken
profiles that the reference refuses. (The reference stays Python on purpose: it is the
independent oracle. The tool is the product.)
"""
import json
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import noise_profile  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def build(compiler, src, out):
    r = subprocess.run([compiler, "build", os.path.join(ROOT, src), "--std", "-o", out], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"build of {src} failed:\n{r.stderr[-800:]}")


def run(exe, text):
    r = subprocess.run([exe], input=text, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def prob(rnd):
    k = rnd.random()
    if k < 0.1:
        return rnd.choice([0, 1, 0.0000005, 0.0000015, 0.0000025, 0.9999995, 0.5])   # ties of the rounding, and the ends
    return round(rnd.random() * rnd.choice([0.001, 0.02, 0.2, 1.0]), rnd.choice([3, 5, 7, 9]))


def ns(rnd):
    return rnd.choice([0, 1, 35, 35.5, 36.4, 0.4, 300, 391.1111111111111, 604.4, 100000])


def profile(rnd):
    n = rnd.randint(1, 20)
    p = {"qubits": n}
    qs = list(range(n))
    pairs = [f"{a}-{b}" for a in range(n) for b in range(n) if a != b]
    for gate, per, pool in (("gate1", "per_qubit", qs), ("gate2", "per_pair", pairs)):
        if rnd.random() < 0.8:
            blk = {}
            if rnd.random() < 0.8:
                blk["default"] = prob(rnd)
            chosen = rnd.sample(pool, min(len(pool), rnd.randint(0, 6)))
            if chosen:
                blk[per] = {str(k): prob(rnd) for k in chosen}
            if rnd.random() < 0.6:
                t = {}
                if rnd.random() < 0.7:
                    t["default"] = ns(rnd)
                chosen = rnd.sample(pool, min(len(pool), rnd.randint(0, 5)))
                if chosen:
                    t[per] = {str(k): ns(rnd) for k in chosen}
                blk["time_ns"] = t
            p[gate] = blk
    if rnd.random() < 0.7:
        c = {}
        if rnd.random() < 0.6:
            t1 = rnd.choice([30000, 55929, 123019.4, 50000])
            c["default"] = [t1, min(2 * t1, rnd.choice([20000, 70000, 95000]))]
        chosen = rnd.sample(qs, min(n, rnd.randint(0, 5)))
        if chosen:
            c["per_qubit"] = {}
            for q in chosen:
                t1 = rnd.choice([30000, 55929, 123019.4, 50000])
                c["per_qubit"][str(q)] = [t1, min(2 * t1, rnd.choice([20000, 70000, 95000, 100000]))]
        p["coherence"] = c
    if rnd.random() < 0.7:
        r = {}
        if rnd.random() < 0.6:
            r["default"] = [prob(rnd), prob(rnd)]
        chosen = rnd.sample(qs, min(n, rnd.randint(0, 5)))
        if chosen:
            r["per_qubit"] = {str(q): [prob(rnd), prob(rnd)] for q in chosen}
        p["readout"] = r
    keys = list(p.items())
    rnd.shuffle(keys)
    return dict(keys)


def breakage(rnd, p):
    q = json.loads(json.dumps(p))
    n = q["qubits"]
    kind = rnd.randrange(9)
    if kind == 0:
        q["qubits"] = rnd.choice([0, 21, -1, 2.5, "3"])
    elif kind == 1:
        q.setdefault("gate1", {})["default"] = rnd.choice([1.5, -0.1, "0.1", True, None])
    elif kind == 2:
        q.setdefault("gate1", {}).setdefault("per_qubit", {})[str(n + rnd.randint(0, 3))] = 0.1
    elif kind == 3:
        q.setdefault("gate2", {}).setdefault("per_pair", {})[rnd.choice(["0-0", "x-1", "0", f"0-{n}", "-"])] = 0.1
    elif kind == 4:
        q.setdefault("readout", {})["default"] = rnd.choice([[0.1], [0.1, 0.2, 0.3], 0.1, [2, 0.1], [0.1, True]])
    elif kind == 5:
        q.setdefault("coherence", {})["default"] = rnd.choice([[100, 250], [0, 5], [100], [-1, 4], [100, "x"]])
    elif kind == 6:
        q.setdefault("gate1", {})["time_ns"] = {"default": rnd.choice([-1, "35", None])}
    elif kind == 7:
        q.setdefault("gate2", {}).setdefault("time_ns", {})["per_pair"] = {rnd.choice(["1-1", "a-b", f"{n}-0"]): 300}
    else:
        q["gate1"] = rnd.choice([[], 3, "x"])
    return q


def reference(p, circuit=None):
    try:
        if circuit is None:
            return "".join(op + "\n" for op in noise_profile.operations(p))
        return noise_profile.apply(p, circuit)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def fake_backends():
    """(name, props) of every fake backend of qiskit-ibm-runtime: real published calibrations."""
    import glob
    import importlib
    import pkgutil
    import qiskit_ibm_runtime.fake_provider.backends as B
    for mi in sorted(pkgutil.iter_modules(B.__path__), key=lambda m: m.name):
        m = importlib.import_module("qiskit_ibm_runtime.fake_provider.backends." + mi.name)
        files = glob.glob(os.path.join(os.path.dirname(m.__file__), "props_*.json"))
        if files:
            yield mi.name, json.load(open(files[0]))


def same_json(a, b, path="", tol=1e-12):
    """None when equal (floats to a relative tolerance, key order included), else where they differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            return f"{path}: keys {list(a)[:6]} vs {list(b)[:6]}"
        for k in a:
            r = same_json(a[k], b[k], f"{path}/{k}", tol)
            if r:
                return r
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: lengths {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            r = same_json(x, y, f"{path}[{i}]", tol)
            if r:
                return r
        return None
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str):
        return None if a == b else f"{path}: {a!r} vs {b!r}"
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if abs(a - b) <= tol * max(1.0, abs(b)) else f"{path}: {a!r} vs {b!r}"
    return None if a == b else f"{path}: {a!r} vs {b!r}"


def calibration_reference(props):
    import calibration_import
    try:
        out = calibration_import.convert(props, f"{props['backend_name']}-{props['last_update_date'][:10]}", {"backend": props["backend_name"], "snapshot": props["last_update_date"], "origin": ""})
    except (KeyError, TypeError, ValueError, StopIteration, ZeroDivisionError):
        return None
    out["source"].pop("origin")
    out.pop("note")
    return out


def check_calibration(compiler):
    exe = os.path.join(tempfile.mkdtemp(prefix="qcalib-"), "qcalib")
    build(compiler, "tools/qcalib.cho", exe)
    failed, checked, clipped, refused = 0, 0, 0, 0
    cases = [(n, p) for n, p in fake_backends()]
    rnd = random.Random(7)
    base = dict(cases)["perth"]
    for k in range(60):
        p = json.loads(json.dumps(base))
        for items in p["qubits"]:
            for it in items:
                if it["name"] in ("T1", "T2"):
                    it["value"] *= rnd.choice([0.2, 1.0, 1.0, 3.0])
                elif it["name"].startswith("prob_meas"):
                    it["value"] = rnd.random() * 0.2
        for g in p["gates"]:
            for par in g["parameters"]:
                if par["name"] == "gate_error":
                    par["value"] = rnd.random() * rnd.choice([0.0005, 0.01, 0.05])
                elif par["name"] == "gate_length" and g["gate"] == "cx":
                    par["value"] = 200 + rnd.random() * 500
        if k % 3 == 0:   # one direction of some cx pairs missing
            p["gates"] = [g for g in p["gates"] if not (g["gate"] == "cx" and g["qubits"][0] > g["qubits"][1] and rnd.random() < 0.5)]
        cases.append((f"perth-fuzz-{k}", p))
    for k in range(20):   # broken: a missing property or gate
        p = json.loads(json.dumps(base))
        what = k % 4
        if what == 0:
            p["qubits"][rnd.randrange(7)] = [it for it in p["qubits"][0] if it["name"] != "T1"]
        elif what == 1:
            p["gates"] = [g for g in p["gates"] if not (g["gate"] == "sx" and g["qubits"] == [rnd.randrange(7)])]
        elif what == 2:
            del p["last_update_date"]
        else:
            for it in p["qubits"][3]:
                if it["name"] == "T2":
                    it["value"] = 0.0
        cases.append((f"perth-broken-{k}", p))
    for name, props in cases:
        want = calibration_reference(props) if len(props["qubits"]) <= 20 else None
        r = subprocess.run([exe], input=json.dumps(props), capture_output=True, text=True)
        if want is None:
            ok, why = r.returncode != 0 and r.stdout == "", "tool accepted what the reference refuses"
            refused += 1
        else:
            got = json.loads(r.stdout) if r.returncode == 0 and r.stdout else None
            if got is None:
                ok, why = False, f"tool refused: {r.stderr.strip()!r}"
            else:
                got["source"].pop("origin")
                got.pop("note")
                d = same_json(got, want)
                ok, why = d is None, d
                checked += 1
                clipped += len(want["conversion"]["t2_clipped_to_2_t1"])
        if not ok:
            failed += 1
            if failed <= 5:
                print(f"FAIL {name}: {why}")
    print(f"{'FAIL' if failed else 'ok  '} qcalib vs calibration_import.py: {checked} calibrations (every fake backend of at most 20 qubits, and fuzzed ones) agree, {clipped} T2 values clipped, {refused} refused by both, {failed} differences")
    return failed


def check_builds(compiler):
    """The tools print the same bytes built by Cranelift, built by LLVM, and interpreted."""
    failed = 0
    cases = {"qcconv": "cho bell\n" + open(os.path.join(ROOT, "tests", "diff", "noise_model_seed1.qc")).read(), "qcalib": open(os.path.join(ROOT, "profiles", "raw", "ibm_perth_props_2024-05-27.json")).read(),
             "qprofile": open(os.path.join(ROOT, "profiles", "ibm_perth_2024-05-27.json")).read() + "\n---\ndm 7\nh 0\ncx 0 1\n"}
    for name, text in cases.items():
        outs = {}
        for backend in ("cranelift", "llvm"):
            exe = os.path.join(tempfile.mkdtemp(prefix=f"{name}-{backend}-"), name)
            r = subprocess.run([compiler, "build", os.path.join(ROOT, "tools", name + ".cho"), "--std", "--backend", backend, "-o", exe], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"build of {name} with {backend} failed:\n{r.stderr[-500:]}")
            outs[backend] = run(exe, text)[1]
        outs["interpreted"] = subprocess.run([compiler, "run", os.path.join(ROOT, "tools", name + ".cho"), "--std"], input=text, capture_output=True, text=True).stdout
        same = len(set(outs.values())) == 1 and outs["llvm"] != ""
        failed += not same
        print(f"{'ok  ' if same else 'FAIL'} {name}: {len(outs['llvm'])} bytes, identical built by Cranelift, built by LLVM, and interpreted")
    return failed


def check_qcconv(compiler):
    """`qcconv` writes exactly what qc_to_cho.py and qc_to_qasm.py write, for every circuit in tests/diff, and refuses the same ways."""
    import qc_to_cho
    import qc_to_qasm
    exe = os.path.join(tempfile.mkdtemp(prefix="qcconv-"), "qcconv")
    build(compiler, "tools/qcconv.cho", exe)
    diff = os.path.join(ROOT, "tests", "diff")
    failed = checked = skipped = 0
    for f in sorted(os.listdir(diff)):
        if not f.endswith(".qc"):
            continue
        name, text = f[:-3], open(os.path.join(diff, f)).read()
        for mode, ref in (("cho " + name, qc_to_cho.convert), ("qasm", qc_to_qasm.convert)):
            want = ref(name)
            r = run(exe, mode + "\n" + text)
            ok = (r[0] == 3 and r[1] == "") if want is None else (r[0] == 0 and r[1] == want)
            failed += not ok
            skipped += want is None
            checked += want is not None
            if not ok and failed <= 5:
                print(f"FAIL qcconv {mode}: exit {r[0]}, {r[2].strip()!r}")
    for label, text in (("no mode line", "n 2\nh 0\n"), ("unknown mode", "x\nn 2\nh 0\n"), ("an unknown operation", "cho a\nn 2\nfoo 0\n"),
                        ("a bad argument", "cho a\nn 2\nh zero\n"), ("too many qubits", "cho a\nn 21\nh 0\n"), ("quiet in a compiled circuit", "cho a\nn 2\nh 0\nquiet\n"),
                        ("an unknown operation in QASM", "qasm\nn 2\nfoo 0\n")):
        r = run(exe, text)
        ok = r[0] in (2,) and r[1] == ""
        failed += not ok
        if not ok:
            print(f"FAIL qcconv should refuse {label}: exit {r[0]}")
    print(f"{'FAIL' if failed else 'ok  '} qcconv vs qc_to_cho.py and qc_to_qasm.py: {checked} files written identically, {skipped} circuits with no such form refused alike, 7 malformed inputs refused, {failed} differences")
    return failed


def main():
    compiler = os.environ.get("CANCHO", "cancho")
    exe = os.path.join(tempfile.mkdtemp(prefix="qprofile-"), "qprofile")
    build(compiler, "tools/qprofile.cho", exe)
    failed = 0

    def same(label, p, circuit=None):
        nonlocal failed
        text = json.dumps(p, indent=rnd_indent(p))
        want = reference(p, circuit)
        got = run(exe, text if circuit is None else text + "\n---\n" + circuit)
        if want is None:
            ok = got[0] != 0 and got[1] == ""
        else:
            ok = got[0] == 0 and got[1] == want
        if not ok:
            failed += 1
            if failed <= 5:
                print(f"FAIL {label}: reference {'refuses' if want is None else 'prints'}, tool exit {got[0]}, stderr {got[2].strip()!r}")
                if want is not None:
                    print("  want", want[:200].replace("\n", "|"))
                    print("  got ", got[1][:200].replace("\n", "|"))
                else:
                    print("  profile", text[:300].replace("\n", " "))
        return ok

    def rnd_indent(p):
        return [None, 1, 2][hash(json.dumps(p, sort_keys=True)) % 3]

    for f in ("example_5q.json", "ibm_perth_2024-05-27.json"):
        p = json.load(open(os.path.join(ROOT, "profiles", f)))
        same(f, p)
        same(f + " with a circuit", p, open(os.path.join(ROOT, "tests", "profile", "ghz5.qc")).read() if f.startswith("example") else "dm 7\nh 0\ncx 0 1\n")
    rnd = random.Random(20241024)
    valid = 0
    for k in range(400):
        p = profile(rnd)
        if reference(p) is None:
            continue
        valid += 1
        same(f"random {k}", p)
        if k % 4 == 0:
            same(f"random {k} with a circuit", p, f"{rnd.choice(['n', 'dm'])} {rnd.randint(1, p['qubits'])}\nh 0\ncx 0 1\nm 0\n")
    refused = 0
    for k in range(200):
        p = breakage(rnd, profile(rnd))
        if reference(p) is None:
            refused += 1
            same(f"broken {k}", p)
    # a circuit that does not fit the profile, and a bad header
    p = profile(random.Random(1))
    same("circuit too large", p, f"n {p['qubits'] + 1}\nh 0\n")
    same("bad header", p, "qubits 3\nh 0\n")
    same("not JSON", {"qubits": 2}, None)
    r = run(exe, "{not json")
    if r[0] == 0 or r[1] != "":
        failed += 1
        print("FAIL malformed JSON was accepted")
    print(f"{'FAIL' if failed else 'ok  '} qprofile vs noise_profile.py: 2 checked-in profiles, {valid} random valid profiles, {refused} refused ones, {failed} differences")
    failed += check_calibration(compiler)
    failed += check_qcconv(compiler)
    failed += check_builds(compiler)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
