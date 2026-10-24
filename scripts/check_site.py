#!/usr/bin/env python3
"""Check that `tools/site/` (cancho) builds the landing page exactly as `scripts/build_site.py` (the reference) does.

    python3 scripts/check_site.py [--compiler cancho]

1. builds `tools/site` and runs it `--live`: it runs `cancho`, `qsim`, `qprofile` and the accept fixtures itself and writes
   docs/index.html and the images;
2. the reference then builds the same page from the same inputs and `--check`s that those files are what it would write,
   byte for byte, and its placeholders (`--dump`) are the ones cancho filled;
3. the sources `tools/site/live.cho` builds `qsim` from are the files of src/.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MODULES = "numfmt text svg facts files replay util live page1 page2 page3 page4 page5 page6 page7 page8 page9 page10 assemble site".split()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    os.chdir(ROOT)
    os.environ["CANCHO"] = args.compiler
    tmp = tempfile.mkdtemp(prefix="check-site-")
    exe = os.path.join(tmp, "site")
    files = [f"tools/site/{m}.cho" for m in MODULES]
    r = subprocess.run([args.compiler, "build", *files, "--std", "-o", exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit("cannot build tools/site:\n" + r.stderr + r.stdout)

    live = open("tools/site/live.cho").read()
    listed = sorted(set(re.findall(r'src/([a-z0-9_]+)\.cho\\0', live.split("fn qsim_sources")[1].split("}")[0])))
    actual = sorted(f[:-4] for f in os.listdir("src") if f.endswith(".cho"))
    if listed != actual:
        sys.exit(f"tools/site/live.cho builds qsim from {listed}, src/ holds {actual}")

    cho_dump = os.path.join(tmp, "cancho-dump.json")
    r = subprocess.run([exe, "--live", "--compiler", args.compiler, "--tmp", os.path.join(tmp, "x-"), "--out", "docs", "--dump", cho_dump], capture_output=True, text=True)
    if r.returncode:
        sys.exit("tools/site --live failed:\n" + r.stderr + r.stdout)
    print("cancho:", r.stdout.strip())

    py_dump = os.path.join(tmp, "python-dump.json")
    r = subprocess.run([sys.executable, "scripts/build_site.py", "--check", "--compiler", args.compiler, "--dump", py_dump], capture_output=True, text=True)
    if r.returncode:
        sys.exit("the reference builder disagrees with the files cancho wrote:\n" + r.stderr + r.stdout)
    print("python:", r.stdout.strip())

    a, b = json.load(open(cho_dump)), json.load(open(py_dump))
    # cancho also names every gallery tile by its title (`tile:TITLE`); the reference has them inside the four galleries.
    galleries = b["GAL_SUPPORTED"] + b["GAL_REFUSED"] + b["GAL_GAPS"] + b["GAL_PLANNED"]
    for m in re.finditer(r'<li class="gtile[^"]*"><h4>(.*?)</h4>.*?</li>', galleries, re.S):
        b["tile:" + html.unescape(re.sub(r"<span.*", "", m.group(1))).strip()] = m.group(0)
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    if diff:
        sys.exit(f"{len(diff)} placeholders differ: {diff[:10]}")
    print(f"{len(a)} placeholders identical; docs/index.html and the images are byte-identical")


if __name__ == "__main__":
    main()
