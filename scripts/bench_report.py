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


def sec1(x):
    """like `sec`, with one decimal below 100 ms (the reader's times are a few milliseconds)"""
    return f"{x * 1000:.1f} ms" if x < 0.1 else sec(x)


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
    f = os.path.join(ROOT, "docs", "data", "bench_features.json")
    if os.path.exists(f):
        out.update(feature_tables(json.load(open(f))))
    return out


def feature_tables(b):
    out = {}
    rows = []
    for key, r in b["qasm"].items():
        rows.append(f"| {key} ({r['gates']} gates, {r['bytes']:,} bytes) | {sec1(r['llvm'])} | {sec1(r['cranelift'])} | {sec1(r['qiskit_loads']) if 'qiskit_loads' in r else 'n/a'} | {sec1(r['llvm_quiet']) if 'llvm_quiet' in r else 'n/a'} |")
    out["qasm"] = "| program | qsim (LLVM) | qsim (Cranelift) | Qiskit `qasm2.loads` alone | qsim (LLVM) `--quiet` |\n|---|---|---|---|---|\n" + "\n".join(rows)
    rows = []
    for k, r in b["expansion"].items():
        if k == "refusal":
            continue
        rows.append(f"| {int(k):,} | {sec1(r['llvm']['defined'])} | {sec1(r['llvm']['written_out'])} | {r['llvm']['per_call_us']:.1f} us | {sec1(r['cranelift']['defined'])} | {sec1(r['cranelift']['written_out'])} | {r['cranelift']['per_call_us']:.1f} us |")
    out["expansion"] = "| calls | defined, LLVM | written out, LLVM | per call, LLVM | defined, Cranelift | written out, Cranelift | per call, Cranelift |\n|---|---|---|---|---|---|---|\n" + "\n".join(rows)
    v = b["variational"]
    rows = [
        f"| VQE, 3 layers, BFGS with the exact gradient ({v['vqe_bfgs']['tool_gradients']} gradients) | {sec1(v['vqe_bfgs']['tool_s'])} | {sec1(v['vqe_bfgs']['scipy_numpy_s'])} | {v['vqe_bfgs']['scipy_numpy_s'] / v['vqe_bfgs']['tool_s']:.1f}x |",
        f"| VQE, 3 layers, SPSA 800 iterations, exact energy ({v['vqe_spsa_800_exact']['evaluations']} evaluations) | {sec1(v['vqe_spsa_800_exact']['tool_s'])} | | |",
        f"| VQE, 3 layers, SPSA 800 iterations, 1,000 shots per basis ({v['vqe_spsa_800_1000_shots']['shots']:,} shots) | {sec1(v['vqe_spsa_800_1000_shots']['tool_s'])} | | |",
    ]
    for layers in (1, 2, 3, 4):
        r = v[f"qaoa_bfgs_{layers}"]
        rows.append(f"| QAOA, {layers} layer{'s' if layers > 1 else ''}, BFGS, 6 starts ({r['tool_gradients']} gradients) | {sec1(r['tool_s'])} | {sec1(r['scipy_numpy_s'])} | {r['scipy_numpy_s'] / r['tool_s']:.1f}x |")
    r = v["qaoa_spsa_2_1000_shots"]
    rows.append(f"| QAOA, 2 layers, SPSA 200 iterations, 6 starts, 1,000 shots ({r['shots']:,} shots) | {sec1(r['tool_s'])} | | |")
    out["variational"] = "| run | cancho (qsim + `opt`, LLVM) | scipy BFGS on numpy, same start and gradient rule | scipy / cancho |\n|---|---|---|---|\n" + "\n".join(rows)
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
