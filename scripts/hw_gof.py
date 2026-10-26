#!/usr/bin/env python3
"""Does the model explain the counts? A chi-square goodness-of-fit test (cancho-stats' `stats test chisq --expected`) of each hardware run against `qsim`'s distribution.

    STATS=path/to/stats python3 scripts/hw_gof.py docs/data/hardware/ibm_kingston-2026-10-26-mirror-from60.json [...]

For each circuit of a job file whose model distribution `hw_model.py run` wrote (`<job>-qsim.json`), the device's counts are tested against
the model's probabilities. An outcome whose expected count is 5 or more is its own level; all the others (seen or not) are pooled into one level
`other`, which is dropped if its expected count is below 5 as well and its mass is then added to the largest level, so that the proportions sum to
1. The statistic, degrees of freedom and p-value are `stats`' (exact statistic, p-value from its own distribution functions, docs/test.md of
cancho-stats). A small p-value says the counts are unlikely under the model: the model is wrong, or the device drifted during the run.

This replaces judging a model by its total-variation distance from the counts against a floor of "0.01 to 0.05" that was only a guess: the test
knows how much distance 2000 shots of the model itself would give. (It does not know what the model leaves out, and a large p-value
does not show the model is right: with few shots it cannot tell a small error from none.)
"""
import json
import os
import subprocess
import sys
import tempfile

STATS = os.environ.get("STATS", "stats")


def test(counts, probs):
    n = sum(counts.values())
    levels = {k: p for k, p in probs.items() if p * n >= 5}
    other = 1.0 - sum(levels.values())
    if other * n < 5:                       # too little mass to be a level of its own: give it to the largest
        top = max(levels, key=levels.get)
        levels[top] += other
        other = 0.0
    seen = {}
    pool = "other" if other > 0 else max(levels, key=levels.get)   # where the outcomes that have no level of their own are counted
    for k, v in counts.items():
        name = k if k in levels else pool
        seen[name] = seen.get(name, 0) + v
    if other > 0:
        levels["other"] = other
    # a level the data never shows has no row, so the tool cannot name it (it takes its levels from the file): its expected mass is given to
    # the largest level. With an expected count of 5 or more that is a probability below 1% under the model itself, and the circumstance a real
    # failure would show first; it makes the test slightly less sensitive to it, not more.
    top = max((k for k in levels if k in seen), key=levels.get)
    for k in [k for k in levels if k not in seen]:
        levels[top] += levels.pop(k)
    names = sorted(levels)                  # the order of the levels by their bytes, as the tool asks
    d = tempfile.mkdtemp(prefix="gof-")
    path = os.path.join(d, "counts.csv")
    with open(path, "w") as f:
        f.write("outcome\n")
        for k in sorted(seen):
            f.write((k + "\n") * seen[k])
    # the tool takes decimals of at most 9 places that add up to exactly 1: round, and give the difference to the largest level
    units = {k: round(levels[k] * 10**9) for k in names}
    units[max(units, key=units.get)] += 10**9 - sum(units.values())
    expected = ",".join(f"{units[k] / 10**9:.9f}" for k in names)
    r = subprocess.run([STATS, "test", "chisq", "--cols", "outcome", "--expected", expected, path], capture_output=True, text=True)
    doc = json.loads(r.stdout)
    if not doc.get("ok"):
        raise SystemExit(f"stats refused: {doc['error']['rule']}: {doc['error']['message']} {doc['error'].get('detail')}")
    t = doc["data"]["tests"][0] if "tests" in doc["data"] else doc["data"]
    return t


def main():
    rows = []
    for path in sys.argv[1:]:
        stem = path[: -len(".json")]
        job = json.load(open(path))
        model = {r["circuit"]: r["qsim"] for r in json.load(open(stem + "-qsim.json"))["rows"]}
        print(f"{job['device']}  {job['date']}  {job['shots']} shots   ({os.path.basename(path)})")
        print(f"  {'circuit':9} {'chi-square':>11} {'df':>3} {'p-value':>9}  levels")
        for c in job["circuits"]:
            counts = {k.replace(" ", ""): v for k, v in c["device"].items()}
            t = test(counts, model[c["circuit"]])
            rows.append({"file": os.path.basename(path), "circuit": c["circuit"], "statistic": t["statistic"], "df": t["df"], "p_value": t["p_value"]})
            print(f"  {c['circuit']:9} {float(t['statistic']):11.1f} {int(t['df']):3d} {float(t['p_value']):9.3g}")
    out = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "gof.json")
    json.dump(rows, open(out, "w"), indent=1)
    print("wrote", os.path.relpath(out, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))


if __name__ == "__main__":
    main()
