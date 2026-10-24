#!/usr/bin/env python3
"""Fill the tables of docs/benchmark.md from docs/data/benchmark.json (so the text cannot disagree with the data).

    python3 scripts/bench_report.py [--check]
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NAMES = {"h_layer": "H on every qubit", "cx_chain": "H, then a CX chain", "rz_layer": "H layer, then Rz on every qubit",
         "random": "random, depth 20", "qft": "QFT"}


def sec(x):
    return f"{x * 1000:.0f} ms" if x < 1 else f"{x:.2f} s"


def tables(d):
    out = {}
    cols = [("qsim_llvm", "qsim (LLVM)"), ("qsim_cranelift", "qsim (Cranelift)"), ("aer_1thread", "Aer, 1 thread"), ("aer_4threads", "Aer, 4 threads"), ("qiskit_statevector", "Qiskit Statevector")]
    rows = []
    for n in d["sizes"][-2:]:
        rows.append(f"| **{n} qubits** | | | | | |")
        for name, label in NAMES.items():
            r = d["workloads"][name][str(n)]
            rows.append(f"| {label} ({r['gates']} gates) | " + " | ".join(sec(r[k]) if k in r else "not run" for k, _ in cols) + " |")
    out["workloads"] = "| workload | " + " | ".join(l for _, l in cols) + " |\n|---|" + "---|" * len(cols) + "\n" + "\n".join(rows)
    n = d["sizes"][-1]
    ratios = []
    for name in NAMES:
        r = d["workloads"][name][str(n)]
        ratios.append((name, r["aer_1thread"] / r["qsim_llvm"], r["aer_4threads"] / r["qsim_llvm"], r["qsim_cranelift"] / r["qsim_llvm"]))
    out["ratios"] = "| workload | Aer 1 thread / qsim (LLVM) | Aer 4 threads / qsim (LLVM) | Cranelift / LLVM |\n|---|---|---|---|\n" + "\n".join(
        f"| {NAMES[nm]} | {a:.2f}x | {b:.2f}x | {c:.1f}x |" for nm, a, b, c in ratios)
    dm = d["noisy"]["density_matrix"]
    out["dm"] = "| qubits | qsim `dm` (LLVM) | qsim `dm` (Cranelift) | Aer density matrix, 1 thread | qsim (LLVM) / Aer |\n|---|---|---|---|---|\n" + "\n".join(
        f"| {k} | {sec(v['qsim_llvm'])} | {sec(v['qsim_cranelift'])} | {sec(v['aer_density_matrix_1thread'])} | {v['qsim_llvm'] / v['aer_density_matrix_1thread']:.1f}x |" for k, v in dm.items())
    k = json.load(open(os.path.join(ROOT, "docs", "data", "benchmark_kernels.json")))
    cols = [("qsim_llvm", "qsim (LLVM)"), ("clang_naive", "C, clang, same loop"), ("gcc_naive", "C, gcc, same loop"), ("clang_tuned", "C, clang, pairs only"), ("gcc_tuned", "C, gcc, pairs only")]
    rows = [f"| {NAMES[w]} | " + " | ".join(sec(r[c]) for c, _ in cols) + f" | {r['qsim_llvm'] / r['clang_naive']:.2f}x | {r['qsim_llvm'] / min(r['clang_tuned'], r['gcc_tuned']):.2f}x |" for w, r in k["workloads"].items()]
    out["kernels"] = "| workload | " + " | ".join(l for _, l in cols) + " | qsim / C, same loop | qsim / best tuned C |\n|---|" + "---|" * (len(cols) + 2) + "\n" + "\n".join(rows)
    return out


def main():
    d = json.load(open(os.path.join(ROOT, "docs", "data", "benchmark.json")))
    path = os.path.join(ROOT, "docs", "benchmark.md")
    text = open(path).read()
    t = tables(d)
    new = text
    for key, body in t.items():
        new = re.sub(rf"(<!-- table:{key} -->\n).*?(<!-- /table -->)", lambda m: m.group(1) + body + "\n" + m.group(2), new, flags=re.S)
    if "--check" in sys.argv:
        sys.exit(0 if new == text else "docs/benchmark.md is out of date with docs/data/benchmark.json")
    open(path, "w").write(new)


if __name__ == "__main__":
    main()
