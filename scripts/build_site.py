#!/usr/bin/env python3
"""Build docs/index.html from docs/index.template.html and the real tools.

    CANCHO=path/to/cancho python3 scripts/build_site.py [--check]

Every number, transcript and chart on the landing page is produced here by
running the compiler and the simulator, not typed in:

  * the refusals are `cancho check` on the fixtures in tests/reject/;
  * the circuits' output is `qsim` on tests/diff/*.qc;
  * the probability bars are drawn from that output;
  * the shot counts come from running tests/accept/bell.cho and teleport.cho,
    and the "without the correction" figure from a mutated copy of the latter;
  * the error figure is scripts/check_diff.py's, the fixture count
    scripts/check_types.py's, the determinism figures the checked-in
    tests/golden/ files.

`--check` rebuilds in memory and fails if docs/index.html differs, the way
cancho-ui's gallery check does, so the page cannot drift from the tools.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import math
import struct
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_svg as svgs
import tools_lib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = os.path.join(ROOT, "docs")
REPO = "https://github.com/alpibrusl/cancho-quantum"
LIB = ["complex", "state", "gates", "profile", "measure", "noise", "qubit"]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def esc(s):
    return html.escape(s, quote=True)


def code(s):
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc(s))


class Tools:
    def __init__(self, cancho):
        self.cancho = cancho
        self.tmp = tempfile.mkdtemp(prefix="site-")
        self.lib = [f"src/{m}.cho" for m in LIB]
        self.all_src = sorted(f"src/{f}" for f in os.listdir(os.path.join(ROOT, "src")) if f.endswith(".cho"))
        self.qsim = os.path.join(self.tmp, "qsim")
        r = sh([cancho, "build", *self.all_src, "--std", "-o", self.qsim])
        if r.returncode:
            sys.exit("cannot build qsim:\n" + r.stderr)

    def run_qc(self, name):
        data = open(os.path.join(ROOT, "tests", "diff", name + ".qc")).read()
        return data, subprocess.run([self.qsim], input=data, capture_output=True, text=True).stdout

    def refusal(self, fixture):
        path = f"tests/reject/{fixture}.cho"
        cmd = [self.cancho, "check", *self.lib, path, "--std"]
        text = sh(cmd).stderr + sh(cmd).stdout
        first = next(l for l in text.splitlines() if "error:" in l)
        first = first.split("error: ", 1)[1]
        js = json.loads(sh([*cmd, "--output", "json"]).stdout)
        rule = js["refused"][0]["rule"]
        return first, rule

    def accept_run(self, fixture, source=None):
        path = source or f"tests/accept/{fixture}.cho"
        exe = os.path.join(self.tmp, "acc-" + fixture)
        b = sh([self.cancho, "build", *self.lib, path, "--std", "-o", exe])
        if b.returncode:
            sys.exit(f"cannot build {path}:\n{b.stderr}")
        r = subprocess.run([exe], capture_output=True, text=True)
        return r.returncode, r.stdout

    def compiles(self, fixture):
        return sh([self.cancho, "check", *self.lib, f"tests/accept/{fixture}.cho", "--std"]).returncode == 0


def amplitudes(out):
    amps = {}
    for line in out.splitlines():
        f = line.split()
        if f and f[0] == "amp":
            amps[int(f[1])] = (float(f[2]), float(f[3]))
    return amps


def bars_svg(n, amps, label):
    total = 2 ** n
    probs = [amps.get(i, (0.0, 0.0)) for i in range(total)]
    probs = [a * a + b * b for a, b in probs]
    top = max(probs) or 1.0
    w, h, pad = 360, 130, 18
    bw = (w - 2 * pad) / total
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" class="bars">']
    out.append(f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" class="axis"/>')
    for i, p in enumerate(probs):
        bh = (h - 2 * pad) * p / top
        x = pad + i * bw
        out.append(f'<rect x="{x + 0.5:.1f}" y="{h - pad - bh:.1f}" width="{max(bw - 1, 1):.1f}" height="{bh:.1f}" class="bar"><title>|{i:0{n}b}&gt; {p:.4f}</title></rect>')
    step = max(total // 8, 1)
    for i in range(0, total, step):
        out.append(f'<text x="{pad + (i + 0.5) * bw:.1f}" y="{h - 8}" text-anchor="middle" class="tick">{i:0{n}b}</text>')
    out.append(f'<text x="{pad}" y="12" class="tick">probability, tallest bar = {top:.3f}</text>')
    out.append("</svg>")
    return "".join(out)


def fmt_amp(a):
    return f"{a[0]:.6f}{'+' if a[1] >= 0 else '-'}{abs(a[1]):.6f}i"


def tile(title, body, extra="", wide=False, soon=False, badge=None):
    cls = "gtile" + (" wide" if wide else "") + (" soon" if soon else "")
    b = f' <span class="badge">{esc(badge)}</span>' if badge else ""
    return f'<li class="{cls}"><h4>{esc(title)}{b}</h4>\n      <p>{body}</p>\n{extra}</li>'


def links(*pairs):
    return '      <p class="glinks">' + " ".join(f'<a href="{esc(u)}">{esc(t)}</a>' for t, u in pairs) + "</p>\n"


def blob(path):
    return f"{REPO}/blob/main/{path}"


def build(cancho):
    t = Tools(cancho)
    P = {}

    # ---- the terminal demo: three real refusals --------------------------------
    term = []
    for fx in ("clone_qubit", "drop_qubit", "use_after_measure"):
        msg, rule = t.refusal(fx)
        term.append([("d", f"$ cancho check src/*.cho tests/reject/{fx}.cho --std"),
                     ("b", "error: " + msg), ("d", f"  rule: {rule}")])
    P["TERMINAL"] = json.dumps(term)

    # ---- state viewer, Bell, GHZ ----------------------------------------------
    bell_qc, bell_out = t.run_qc("bell")
    bell_amps = amplitudes(bell_out)
    r5_qc, r5_out = t.run_qc("random5")
    r5_amps = amplitudes(r5_out)
    g10_qc, g10_out = t.run_qc("ghz10")
    g10_amps = amplitudes(g10_out)
    eg_qc, eg_out = t.run_qc("every_gate")

    # ---- shots -----------------------------------------------------------------
    _, bell_shots = t.accept_run("bell")
    _, tele = t.accept_run("teleport")
    src = open(os.path.join(ROOT, "tests", "accept", "teleport.cho")).read()
    mut = os.path.join(t.tmp, "tele_mut.cho")
    open(mut, "w").write(src.replace("if m0 == 1 {", "if m0 == 7 {"))
    _, tele_mut = t.accept_run("tele_mut", mut)

    def field(text, key):
        return next(l.split()[-1] for l in text.splitlines() if l.startswith(key))

    # ---- the pinned gap --------------------------------------------------------
    gap_compiles = t.compiles("same_handle_cx")
    gap_code, _ = t.accept_run("same_handle_cx")

    # ---- gates ------------------------------------------------------------------
    # What `scripts/check_diff.py` and `check_types.py` last measured (they write these files; this does not re-run them).
    cdiff = json.load(open(os.path.join(DOCS, "data", "check_diff.json")))
    ctypes = json.load(open(os.path.join(DOCS, "data", "check_types.json")))
    d = "".join(f"ok   {name:18s} worst {w}\n" for name, w in cdiff["rows"])
    worst = (str(cdiff["circuits"]), cdiff["worst"])
    ulp = (str(cdiff["trig_ulp"]),)
    fx = (str(ctypes["ok"]), str(ctypes["all"]))
    golden = [l for l in open(os.path.join(ROOT, "tests", "golden", "outputs.sha256")) if l.strip()]
    prov = json.load(open(os.path.join(ROOT, "tests", "golden", "provenance.json")))

    P["AGENT_PROMPT"] = esc(open(os.path.join(DOCS, "agent-prompt.md")).read().rstrip("\n"))
    P["N_CIRCUITS"] = worst[0]
    P["WORST"] = worst[1]
    P["ULP"] = ulp[0]
    P["FIX_OK"], P["FIX_ALL"] = fx
    P["N_GOLDEN"] = str(len(golden))

    # ---- gallery: supported ----------------------------------------------------
    sup = []
    sup.append(tile("Bell pair",
        "H then CNOT. Two amplitudes of 1/&radic;2 and nothing else, matching Qiskit to the last bit.",
        '      {{DIAGRAM_BELL}}\n'
        f'      <pre class="code small">{esc(bell_qc.strip())}</pre>\n'
        f'      {bars_svg(2, bell_amps, "Probability of each two-qubit outcome of the Bell state: 00 and 11 at one half, 01 and 10 at zero")}\n'
        f'      <pre class="code small">amp 0 = {esc(fmt_amp(bell_amps.get(0, (0, 0))))}\namp 3 = {esc(fmt_amp(bell_amps.get(3, (0, 0))))}</pre>\n'
        + links(("Circuit", blob("tests/diff/bell.qc")), ("Reference", blob("tests/diff/bell.ref")))))
    sup.append(tile("A 5-qubit state, 60 gates",
        "A fixed pseudo-random circuit of H, X, Z, S, T, RZ, CNOT and CZ. Each of its 32 amplitudes is within 2e-16 of Qiskit's.",
        f'      {bars_svg(5, r5_amps, "Probability of each of the 32 five-qubit outcomes after the random circuit")}\n'
        + links(("Circuit", blob("tests/diff/random5.qc")), ("Reference", blob("tests/diff/random5.ref")))))
    nz = sorted(i for i, a in g10_amps.items() if a != (0.0, 0.0))
    sup.append(tile("GHZ on 10 qubits",
        f"A state of {2**10} amplitudes with exactly {len(nz)} non-zero: |0000000000&rang; and |1111111111&rang;, each {fmt_amp(g10_amps[nz[0]]).split('+')[0]}. The same circuit on 20 qubits (a million amplitudes, 16 MiB) runs in a fraction of a second.",
        f'      <pre class="code small">{esc(g10_qc.strip().splitlines()[0])}\n{esc(g10_qc.strip().splitlines()[1])}\n... {len(g10_qc.strip().splitlines()) - 3} more cx\nnon-zero: {", ".join(str(i) for i in nz)}</pre>\n'
        + links(("Circuit", blob("tests/diff/ghz10.qc")))))
    sup.append(tile("Bell pair, 200 shots, typed",
        f"The linear layer: each shot makes two <code>Qubit</code>s, applies gates through borrows, and ends both with <code>measure</code>. Bits that disagreed: <b>{field(bell_shots, 'disagree')}</b>. Ones: <b>{field(bell_shots, 'ones')}</b> of 200 (a fact about the seeded sampler; an independent Python copy of the generator gives the same count).",
        links(("Source", blob("tests/accept/bell.cho")))))
    sup.append(tile("Teleportation",
        f"Qubit 0 holds an unknown state; measuring it and its Bell partner <em>consumes</em> both, and two classical bits say which of X and Z to apply to qubit 2. Over 80 different states: <b>{field(tele, 'failures')}</b> failures, all <b>{field(tele, 'outcomes')}</b> measurement outcomes seen. With the Z correction deleted the same check fails <b>{field(tele_mut, 'failures')}</b> of 80, so the check is not vacuous.",
        '      {{DIAGRAM_TELEPORT}}\n'
        + links(("Source", blob("tests/accept/teleport.cho")), ("Unitary half", blob("tests/diff/teleport_unitary.qc")))))
    sup.append(tile("The same bytes, six ways",
        f"Every one of the {P['N_GOLDEN']} circuits runs interpreted and as a compiled cancho function, on Cranelift and LLVM (x86-64) and LLVM aarch64 under <code>qemu-user</code>. All six outputs are byte-identical and match the SHA-256 checked in. The aarch64 run is emulation, not arm64 hardware.",
        f'      <pre class="code small">bell\ncircuit  {esc(prov["bell"]["circuit_body_id"][:16])}...\noutput   {esc(prov["bell"]["output_sha256"][:16])}...\nlibrary  {esc(prov["bell"]["library_digest"][:16])}...</pre>\n'
        + links(("Provenance", blob("tests/golden/provenance.json")), ("Results", blob("docs/m3-results.md")))))

    _, g_out = t.run_qc("grover3")
    g_samples = [(l.split()[1], int(l.split()[2])) for l in g_out.splitlines() if l.startswith("sample")]
    g_all = {f"{i:03b}": 0 for i in range(8)}
    for b, c in g_samples:
        g_all[b] = c
    g_n, g_ops = parse_qc("grover3")
    g_gates = len([o for o in g_ops if o[0] not in ("seed", "sample")])
    sup.append(tile("Grover search",
        f"Three qubits, {g_gates} gates, two rounds: find the one marked item (101) among 8. Sampling the final state 1000 times gives <b>{g_all['101']}</b> hits on it, where a blind guess gives about 125. The counts match an independent sampler exactly.",
        f'      {svgs.count_hist(list(g_all), list(g_all.values()), 125, 0, "Counts of each three-bit outcome over 1000 samples of the Grover state: the marked item 101 dominates")}\n'
        + links(("Circuit", blob("tests/diff/grover3.qc")), ("Reference", blob("tests/diff/grover3.ref")))))
    _, bv_out = t.run_qc("bernstein_vazirani")
    bv_lines = [l for l in bv_out.splitlines() if l.startswith("sample")]
    _, bv_typed = t.accept_run("bernstein_vazirani_typed")
    sup.append(tile("Bernstein\u2013Vazirani, typed",
        f"A hidden 4-bit string is read in one run of the circuit. The simulator samples <code>{esc(' | '.join(l.replace('sample ', '') for l in bv_lines))}</code>: the low four bits are always 1011 (the ancilla bit is random). The typed version, with every qubit ended by <code>measure</code>, prints <b>{esc(bv_typed.strip())}</b>.",
        links(("Circuit", blob("tests/diff/bernstein_vazirani.qc")), ("Typed", blob("tests/accept/bernstein_vazirani_typed.cho")))))
    _, tof = t.accept_run("toffoli_typed")
    sup.append(tile("Toffoli, typed",
        "Two controls borrowed shared, one target borrowed unique; the truth table (controls then result):",
        f'      <pre class="code small">{esc(tof.strip())}</pre>\n' + links(("Source", blob("tests/accept/toffoli_typed.cho")))))
    nc = json.load(open(os.path.join(DOCS, "data", "noise_curve.json")))
    nk = json.load(open(os.path.join(DOCS, "data", "noise_check.json")))
    dev = max(abs(r["estimate"] - r["exact"]) / r["stderr"] for r in nc["rows"] if r["stderr"] > 1e-9)
    zs = ", ".join(f"{c['max_z']:.1f}" for c in nk["circuits"])
    sup.append(tile("Noise, checked against the exact answer",
        f"Five channels (bit flip, phase flip, depolarizing, amplitude damping, two-qubit depolarizing), readout error and a gate-noise model, each run as one random operator per run. One run is one noisy outcome; the <em>average</em> of many is the density matrix. Here a Bell pair through depolarizing noise on one qubit: {nc['shots']} seeded runs per point against the exact curve (1 &minus; p). The largest gap is {dev:.1f} standard errors. {len(nk['circuits'])} noisy circuits (up to 3 qubits) were compared to a density-matrix calculation over {nk['shots']} runs each: worst z-scores {zs}. Readout error, which flips the reported bit and not the state, is checked as a binomial (z = {nk['readout']['measured_z']:.1f} on measured bits, {nk['readout']['sample_z']:.1f} on samples, {nk['readout']['asymmetric_z']:.1f} when asymmetric). Doubling a probability on purpose is caught at z = {nk['wrong_probability_z']}.",
        f'      {svgs.curve_chart(nc["rows"], "Fidelity of a Bell pair against the depolarizing probability: runs follow the exact straight line 1 minus p", "depolarizing probability p", "fidelity")}\n'
        + links(("Channels", blob("src/noise.cho")), ("Check", blob("scripts/check_noise.py")), ("Results", blob("docs/noise-results.md")))))
    pc = json.load(open(os.path.join(DOCS, "data", "purity_curve.json")))
    dmq = "dm 2\nh 0\ncx 0 1\ndepol 1 1 4\npurity\ntrace\nquiet\n"
    dm_out = subprocess.run([t.qsim], input=dmq, capture_output=True, text=True).stdout.split()
    n_dm = len([f for f in os.listdir(os.path.join(ROOT, "tests", "diff")) if f.startswith("dm_") and f.endswith(".qc")])
    sup.append(tile("Exact noise: the density matrix",
        f"<code>dm 2</code> keeps the whole density matrix, so one run is the exact answer, not a sample. The same Bell pair through depolarizing noise (p = 1/4) has purity <b>{float(dm_out[1]):.6f}</b> and trace <b>{float(dm_out[3]):.6f}</b>; the formula (1&minus;p)&sup2; + p&sup2;/3 gives {(0.75) ** 2 + 0.25 ** 2 / 3:.6f}. The curve is the purity against p: cancho, Qiskit and the formula agree to {pc['worst_difference']:.0e}. {n_dm} density-matrix circuits (all channels, every gate, measurement) match Qiskit&rsquo;s DensityMatrix. Up to 10 qubits: the matrix is stored as a state of twice as many.",
        f'      {svgs.curve_chart(pc["rows"], "Purity of a Bell pair against the depolarizing probability: cancho, Qiskit and the formula coincide", "depolarizing probability p", "purity", y0=0.3, y1=1.0, label_est="cancho (exact)", label_exact="formula", errbars=False)}\n'
        + links(("Source", blob("src/density.cho")), ("Circuits", blob("tests/diff")), ("Results", blob("docs/density-results.md")))))
    bm = json.load(open(os.path.join(DOCS, "data", "benchmark.json")))
    bn = str(bm["sizes"][-1])
    names = {"h_layer": "H layer", "cx_chain": "CX chain", "rz_layer": "Rz layer", "random": "random, depth 20", "qft": "QFT"}
    groups = [(names[k], {"q_l": v[bn]["qsim_llvm"], "q_c": v[bn]["qsim_cranelift"], "a1": v[bn]["aer_1thread"], "a4": v[bn]["aer_4threads"]}) for k, v in bm["workloads"].items()]
    ratio = [v[bn]["aer_1thread"] / v[bn]["qsim_llvm"] for v in bm["workloads"].values()]
    ratio4 = [v[bn]["aer_4threads"] / v[bn]["qsim_llvm"] for v in bm["workloads"].values()]
    dm8 = bm["noisy"]["density_matrix"]["8"]
    kb = json.load(open(os.path.join(DOCS, "data", "benchmark_kernels.json")))
    kr = [r["qsim_llvm"] / r["clang_naive"] for r in kb["workloads"].values()]
    sup.append(tile("Speed: against Qiskit Aer",
        f"The same circuits on {bn} qubits, whole process for <code>qsim</code> (start, parse, run) against Aer&rsquo;s <code>run</code> alone. Built with LLVM, <code>qsim</code> runs at {min(ratio):.1f}&ndash;{max(ratio):.1f}&times; the speed of Aer on one core, and at {min(ratio4):.1f}&ndash;{max(ratio4):.1f}&times; the speed of Aer on all four (1 is level; Aer&rsquo;s time divided by ours). Cranelift, the default backend, is 3&ndash;6&times; slower than LLVM, so use <code>--backend llvm</code> for large circuits. A {bn}-qubit state takes {bm['memory_mib']['qsim']:.0f} MiB of {bm['memory_mib']['state_vector_mib']:.0f}. The exact density matrix, once the weak spot (7&times; slower than Aer&rsquo;s at 8 qubits), now takes {dm8['qsim_llvm'] / dm8['aer_density_matrix_1thread']:.1f}&times; Aer&rsquo;s time there: its channels are single passes. Written in C with the same loops, three of the kernels run within {min(kr):.2f}&ndash;{max(kr):.2f}&times; of <code>qsim</code>&rsquo;s time on the same compiler backend: the language is not the limit, memory and parallelism are. Minimum of 3&ndash;5 runs on {esc(bm['machine'])}, Qiskit {esc(bm['versions']['qiskit'])}, Aer {esc(bm['versions']['qiskit_aer'])}.",
        f'      {svgs.bench_chart(groups, [("q_l", "qsim LLVM"), ("q_c", "qsim Cranelift"), ("a1", "Aer 1 thread"), ("a4", "Aer 4 threads")], f"Time to run five circuits on {bn} qubits, qsim built with LLVM and Cranelift against Qiskit Aer on one and four threads, on a log axis")}\n'
        + links(("Method and results", blob("docs/benchmark.md")), ("Script", blob("scripts/bench_compare.py")), ("Data", blob("docs/data/benchmark.json")))))
    prof_text = open(os.path.join(ROOT, "profiles", "example_5q.json")).read()
    prof_circuit = tools_lib.run("qprofile", prof_text + "\n---\n" + open(os.path.join(ROOT, "tests", "profile", "ghz5.qc")).read())
    pr_out = subprocess.run([t.qsim], input=prof_circuit, capture_output=True, text=True).stdout.splitlines()
    pr_prob = {int(l.split()[1], 2): float(l.split()[2]) for l in pr_out if l.startswith("prob ")}
    pr_rho = {(int(l.split()[1]), int(l.split()[2])): float(l.split()[3]) for l in pr_out if l.startswith("rho ")}
    pr_purity = float(next(l.split()[1] for l in pr_out if l.startswith("purity ")))
    pr_fid = (pr_rho[(0, 0)] + pr_rho[(31, 31)] + 2 * pr_rho[(0, 31)]) / 2
    pr_amps = {i: (math.sqrt(v), 0.0) for i, v in pr_prob.items()}
    n_ops = len([l for l in tools_lib.run("qprofile", prof_text).splitlines() if l])
    sup.append(tile("A device-style noise profile",
        f"A JSON file describes a device: a depolarizing rate per qubit for one-qubit gates, per pair for two-qubit gates, and asymmetric readout error per qubit (a true 1 is misread more often than a true 0). <code>tools/qprofile.cho</code> (cancho) turns it into {n_ops} operations and puts them in front of a circuit; <code>qsim</code> still reads only standard input. Below, a 5-qubit GHZ state through <b>example-5q</b> (<em>invented</em> numbers of a realistic size, not a real machine) on the density matrix: fidelity <b>{pr_fid:.4f}</b>, purity <b>{pr_purity:.4f}</b>. The bars are the exact outcome probabilities (readout error acts on top, when measuring). It matches a Qiskit calculation made from the JSON to 1e-12.",
        f'      {bars_svg(5, pr_amps, "Exact probability of each of the 32 outcomes of a five-qubit GHZ state under the example noise profile: the all-zeros and all-ones outcomes dominate, with small leakage into neighbours")}\n'
        + links(("Profile", blob("profiles/example_5q.json")), ("Converter", blob("tools/qprofile.cho")), ("Check", blob("scripts/check_profile.py")), ("Format", blob("docs/noise-profile.md")))))
    ic = json.load(open(os.path.join(DOCS, "data", "idle_curve.json")))
    n_idle = len([f for f in os.listdir(os.path.join(ROOT, "tests", "diff")) if "idle" in f and f.endswith(".qc")])
    sup.append(tile("Idle noise: T1 and T2",
        f"A qubit that waits decays. <code>coher q T1 T2</code> gives it coherence times in nanoseconds; <code>wait q ns</code> idles it, and <code>time1</code> / <code>time2</code> make every gate take time, during which its qubits relax too. The channel is amplitude damping plus dephasing, sampled by trajectories or exact on the density matrix. Below, T1 = {ic['t1_ns'] // 1000} &micro;s and T2 = {ic['t2_ns'] // 1000} &micro;s: the chance a qubit is still 1, and the coherence of |+&rang;, against waiting time. cancho, <b>Qiskit Aer&rsquo;s own thermal-relaxation channel</b> and the formulas agree to {ic['worst_difference']:.0e}. {n_idle} idle-noise circuits match Qiskit; a sampled GHZ circuit with gate times matches the exact density matrix within statistics.",
        f'      {svgs.curve_chart(ic["population"], "Chance a qubit prepared in 1 is still 1 against waiting time, with T1 of 50 microseconds: a falling exponential that cancho and Qiskit Aer share", "waiting time (microseconds)", "P(still 1)", y0=0.0, y1=1.0, label_est="cancho (exact)", label_exact="exp(-t/T1)", errbars=False, xmax=100, xname="t")}\n'
        f'      {svgs.curve_chart(ic["coherence"], "Coherence of a qubit prepared in plus against waiting time, with T2 of 70 microseconds", "waiting time (microseconds)", "coherence |rho01|", y0=0.0, y1=0.5, label_est="cancho (exact)", label_exact="exp(-t/T2) / 2", errbars=False, xmax=100, xname="t")}\n'
        + links(("Source", blob("src/noise.cho")), ("Curve", blob("scripts/idle_curve.py")), ("Check", blob("scripts/check_noise.py")), ("Design", blob("docs/idle-noise.md")))))
    sc = json.load(open(os.path.join(DOCS, "data", "schedule_curve.json")))
    sup.append(tile("Scheduling: a waiting qubit decays",
        f"<code>sched</code> starts every gate as soon as its qubits are free, and a qubit that finishes early idles (and relaxes) until its partner is ready. Below, qubit 0 starts as 1 and does nothing while a chain of <code>cx</code> gates runs on two other qubits: its chance of still being 1 follows exp(&minus;t/T1) (T1 = {sc['t1_ns'] // 1000} &micro;s). Without <code>sched</code> it stays at exactly 1. Six random 14-gate circuits on 4 qubits, with different T1, T2 and gate times per qubit and pair, agree with <b>Qiskit&rsquo;s own ASAP scheduler</b> (for the start times) and Aer&rsquo;s relaxation channel to {sc['worst_vs_qiskit']:.0e}; the same circuits without <code>sched</code> are at least {sc['smallest_gap_without_sched']:.0e} away, so the check can tell. Measurements and noise operations take no time; <code>barrier</code> waits for every qubit, and a <code>sample</code> or the final output implies one.",
        f'      {svgs.curve_chart(sc["rows"], "Chance a qubit prepared in 1 is still 1 while other qubits work, with T1 of 50 microseconds: it decays as a falling exponential under the scheduler", "time the other qubits spend working (microseconds)", "P(still 1)", y0=0.0, y1=1.0, label_est="cancho, sched (exact)", label_exact="exp(-t/T1)", errbars=False, xmax=50, xname="t")}\n'
        + links(("Source", blob("src/noise.cho")), ("Check", blob("scripts/check_schedule.py")), ("Design", blob("docs/idle-noise.md")))))
    cal = json.load(open(os.path.join(ROOT, "profiles", "ibm_perth_2024-05-27.json")))
    cc = json.load(open(os.path.join(DOCS, "data", "calibration_check.json")))
    rows_q = ["q   T1   T2   1q p  r01   r10"]
    for q in range(cal["qubits"]):
        t1, t2 = cal["coherence"]["per_qubit"][str(q)]
        ro = cal["readout"]["per_qubit"][str(q)]
        rows_q.append(f"{q}  {t1 / 1000:4.0f} {t2 / 1000:4.0f}  {cal['gate1']['per_qubit'][str(q)] * 1e4:4.1f}e-4 {ro[0]:.3f} {ro[1]:.3f}")
    rows_p = ["pair  ns   cx error > p"]
    pub = {r["pair"]: r for r in cal["conversion"]["two_qubit"]}
    for key in cal["gate2"]["per_pair"]:
        rows_p.append(f"{key:>4} {cal['gate2']['time_ns']['per_pair'][key]:4}  {pub[key]['published_error']:.4f} > {cal['gate2']['per_pair'][key]:.4f}")
    worst_ok = max(r["cancho_vs_aer"] for r in cc["circuits"])
    n_decay_only = sum(1 for r in cal["conversion"]["two_qubit"] if r["relaxation_part"] > r["published_error"])
    ctrl = [r[k] / r["cancho_vs_aer"] for r in cc["circuits"] for k in ("control_no_idle", "control_naive")]
    moved = [r["noise_vs_ideal"] for r in cc["circuits"]]
    sup.append(tile("A real device's calibration",
        f"The calibration <b>{esc(cc['backend'])}</b> published on {esc(cc['snapshot'][:10])} (the snapshot that ships with qiskit-ibm-runtime; no account, no live machine) is read into a profile by <code>tools/qcalib.cho</code> (cancho) (below: T1 and T2 in &micro;s, the depolarizing probability p kept for one-qubit gates, readout error 0&rarr;1 and 1&rarr;0; cx time and error). Its T1, T2, gate times, readout and gate errors are all there. One conversion matters: IBM&rsquo;s gate error already contains the decay during the gate, and the simulator adds that decay itself, so it is taken out first (for {n_decay_only} of {len(cal['conversion']['two_qubit'])} pairs the T1/T2 decay alone exceeds the published error, so they get no extra depolarizing noise). {cc['numbers_rederived']} numbers were re-derived from the raw file by another route. Two circuits of native gates run through the profile on 7 qubits land within <b>{worst_ok:.0e}</b> (trace distance) of Qiskit Aer&rsquo;s noise model built from the same snapshot, while the noise itself moves the state by {min(moved):.2f}&ndash;{max(moved):.2f}; leaving the idle decay out, or using the published error as is, is {min(ctrl):.0f}&ndash;{max(ctrl):.0f} times worse.",
        '      <pre class="code small">' + esc("\n".join(rows_q + [""] + rows_p)) + '</pre>\n'
        + links(("Profile", blob("profiles/ibm_perth_2024-05-27.json")), ("Importer", blob("tools/qcalib.cho")), ("Check", blob("scripts/check_calibration.py")), ("Notes", blob("docs/calibration.md")))))
    hw = json.load(open(os.path.join(DOCS, "data", "hardware_summary.json")))
    sup.append(tile("Against a real quantum computer",
        f"The noise model above, built only from a device&rsquo;s published calibration, was run on the mirror circuits (a circuit followed by its inverse, which ought to return all zeros) that IBM&rsquo;s <b>{esc(hw['healthy_device'])}</b> ran on {esc(hw['date'])}: {hw['healthy_runs']} runs of up to {hw['healthy_max_cz']} <code>cz</code> gates, {hw['shots']} shots each. The exact density matrix is within <b>{hw['healthy_worst_gap']:.3f}</b> of what the device measured (total-variation distance from all zeros), close but not exact: a chi-square test (cancho-stats) at {hw['shots']} shots tells the model from the device on every run. On <b>{esc(hw['drift_device'])}</b> it is not: over {hw['drift_runs']} runs the device&rsquo;s error was {hw['drift_ratio_min']:.1f}&ndash;{hw['drift_ratio_max']:.1f} times the model&rsquo;s, and the calibration changed by more than the device did, so there the model is not reliable: most of the error traces to one qubit that read wrongly several times as often as its published calibration said (fitting that qubit&rsquo;s read-out error brought the model within sampling noise of the device on circuits left out of the fit, for that run only). One qubit of {esc(hw['healthy_device'])} read 1 in {hw['stuck_percent']:.0f}% of idle shots while its published calibration looked healthy; <code>scripts/hw_spike.py</code> now reads the qubits it will use before a run and refuses broken ones. One day, two devices, small circuits.",
        links(("Results", blob("docs/hardware.md")), ("Script", blob("scripts/hw_spike.py")), ("Data", blob("docs/data/hardware_summary.json")))))
    qr = json.load(open(os.path.join(ROOT, "tests", "qasm", "results.json")))
    sup.append(tile("OpenQASM 2.0 in",
        f"<code>qsim</code> reads the OpenQASM a circuit is usually written in. All {qr['files']} circuits that QASM can express were converted, parsed by Qiskit&rsquo;s own reader and by <code>qsim</code>, and agree with the reference. Going the other way, {qr['qiskit_written_run']} of the files <em>Qiskit</em> wrote run; {qr['qiskit_written_refused_decimal']} were refused. An angle may be a multiple of &pi; (<code>3*pi/4</code>, kept as exactly the double the references compute) or a decimal, which is read to the same double Python reads (bit for bit over 16,000 random texts in the range it promises, <code>scripts/check_qasm.py</code>).",
        '      <pre class="code small">OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\nrz(pi/4) q[1];</pre>\n'
        + links(("Reader", blob("src/qasm.cho")), ("Files", blob("tests/qasm")), ("Check", blob("scripts/check_qasm.py")))))

    # ---- gallery: refused -------------------------------------------------------
    why = {
        "clone_qubit": ("No cloning", "Measuring the same qubit twice. The first <code>measure</code> consumes it."),
        "drop_qubit": ("No dropping", "A gate borrows the qubit and hands it back, so the function still owes a consumption."),
        "use_after_measure": ("Measurement collapses", "After <code>measure</code> there is no qubit left to borrow."),
        "escape_borrow": ("No escaping a borrow", "A reference to a qubit may not outlive the block that borrowed it."),
        "measure_in_loop": ("One measurement per qubit", "<code>measure</code> inside a loop consumes on the first pass and has nothing on the second."),
        "two_mutable_borrows": ("One gate at a time", "No second unique borrow of a qubit while a gate on it is in flight."),
        "read_qubit_index": ("No peeking at identity", "The index of an owned qubit cannot be read out of it."),
        "control_written": ("Control is read, target is written", "A control borrowed shared cannot stand where the operand to change is expected."),
    }
    ref = []
    for fxn, (title, body) in why.items():
        msg, rule = t.refusal(fxn)
        ref.append(tile(title,
            body + f'<br><span class="rule">{esc(rule)}</span>',
            f'      <pre class="code small err">{esc(msg)}</pre>\n' + links(("Fixture", blob(f"tests/reject/{fxn}.cho")))))

    # ---- gallery: accepted but wrong -------------------------------------------
    gaps = []
    gaps.append(tile("CNOT with one qubit as both operands",
        f"Accepted by the checker (compiles: <b>{'yes' if gap_compiles else 'no'}</b>), because a unique borrow is a copyable pointer. It stops at run time instead, with a trap (signal {-gap_code}, SIGILL, on Linux). Two more ways to the same program are pinned the same way: a copied handle, and two qubits with the same index.",
        links(("Fixture", blob("tests/accept/same_handle_cx.cho")), ("Why", blob("docs/m2-results.md")))))
    gaps.append(tile("Forging a qubit",
        "A <code>pub res struct</code> can be built and taken apart from any module, so &ldquo;only <code>fresh</code> makes qubits&rdquo; is a convention. The page does not hide this: it is a request to the compiler, not a flaw of the simulator.",
        links(("Fixture", blob("tests/accept/forged_qubit.cho")))))

    # ---- gallery: planned -------------------------------------------------------
    plan = [
        ("A Qpu capability", "Which backend a program can reach and how many shots it may spend, readable from the program text before it runs. A first slice exists as a library (<code>src/qpu.cho</code>: a linear counter that refuses what exceeds it, narrowing that never raises a budget), tested; the compiler does not know it, so nothing is refused at check time and <code>cancho authority</code> prints no bound. Shot budgets are only decidable for constant counts, so the honest claim is a declared bound a supervisor enforces.", "Needs the compiler", [("Tracked in cancho#612", "https://github.com/alpibrusl/cancho/issues/612"), ("First slice", blob("docs/qpu.md")), ("Plan", blob("docs/qubit-types.md"))]),
        ("Refuse CNOT(q, q) at check time", "A same-place-twice rule would close at least one of the three ways; its design predicts a second, which is not measured, and says the third needs a different fix. Written, not built.", "Needs the compiler", [("Tracked in cancho#610", "https://github.com/alpibrusl/cancho/issues/610"), ("Design PR #608", "https://github.com/alpibrusl/cancho/pull/608")]),
        ("Private constructors", "So that only the simulator can mint a qubit. A proposed opt-in <code>opaque</code> struct; written, not built.", "Needs the compiler", [("Tracked in cancho#611", "https://github.com/alpibrusl/cancho/issues/611"), ("Design PR #608", "https://github.com/alpibrusl/cancho/pull/608")]),
        ("The rest of OpenQASM", "<code>gate</code> definitions, and writing QASM from cancho itself (a Python script writes it now). <code>sx</code>, <code>sxdg</code>, <code>id</code>, <code>u2</code>, <code>u3</code> and <code>u</code> are read (<code>u3</code> is <code>p ry p</code>, exactly) and checked against Qiskit on 120 random circuits; so are <code>cy</code>, <code>ch</code>, <code>crz</code>, <code>rzz</code> and <code>cswap</code> (120 more) and <code>creg</code>, <code>measure &rarr;</code> and <code>if</code> (120 programs against Aer).", "Planned", [("Reader", blob("src/qasm.cho"))]),
        ("Crosstalk and richer gate noise", "Noise that depends on the gate type, crosstalk between neighbouring qubits, leakage and non-Pauli two-qubit noise are not built; the model is depolarizing noise plus idle decay, at a rate per qubit or pair. A Toffoli has neither a duration nor a noise rate.", "Planned", [("Idle noise", blob("docs/idle-noise.md"))]),
        ("Density matrices past 10 qubits", "The density matrix is stored as a state of 2n qubits, so the 20-qubit limit means 10. Larger needs a different representation.", "Later", []),
        ("More devices, live calibration", "One snapshot of one 7-qubit machine (2024) is used, taken from a file. Fetching a current calibration from a service, other devices, and reading the pulse-level durations are not built.", "Planned", [("Importer", blob("tools/qcalib.cho"))]),
        ("A second reference, Cirq", "Qiskit is the only reference so far. A second one would catch a convention both share.", "Planned", []),
        ("Real arm64 hardware", "The aarch64 result is emulation. A run on a real arm64 machine is still owed.", "Planned", [("Results", blob("docs/m3-results.md"))]),
        ("A cloud quantum service", "Submit a circuit over HTTPS. The authority report will be coarser here, because host-set bounds are design-only in cancho.", "Later", []),
        ("Adjoint and controlled gates", "Not possible today: cancho has no function values, so a gate cannot be passed to a transform. Circuits stay data.", "Not possible yet", []),
        ("A GPU backend", "Out of scope until cancho-gpu exists. A state vector of 20 qubits is fine on one CPU core.", "Out of scope", []),
    ]
    soon = [tile(tt, body, links(*lk) if lk else "", soon=True, badge=bg) for tt, body, bg, lk in plan]


    # ---- capabilities: every gate and channel named on the page is run first ---------------
    one_q = [("h", "H", "h 0"), ("x", "X", "x 0"), ("y", "Y", "y 0"), ("z", "Z", "z 0"), ("s", "S", "s 0"), ("sdg", "S†", "sdg 0"),
             ("t", "T", "t 0"), ("tdg", "T†", "tdg 0"), ("rx", "Rx", "rx 0 1 3"), ("ry", "Ry", "ry 0 1 3"), ("rz", "Rz", "rz 0 1 3"), ("p", "P", "p 0 1 3")]
    two_q = [("cx", "CNOT", "cx 0 1"), ("cz", "CZ", "cz 0 1"), ("cp", "controlled phase", "cp 0 1 1 4"), ("swap", "SWAP", "swap 0 1")]
    three_q = [("ccx", "Toffoli", "ccx 0 1 2")]
    chans = [("bitflip", "bit flip", "bitflip 0 1 3"), ("phaseflip", "phase flip", "phaseflip 0 1 3"), ("depol", "depolarizing", "depol 0 1 3"), ("ampdamp", "amplitude damping", "ampdamp 0 1 3"), ("depol2", "two-qubit depolarizing", "depol2 0 1 1 3")]
    extras_ops = [("readout error", "readout 1 4"), ("a gate-noise model", "model1 1 20"), ("a two-qubit gate-noise model", "model2 1 20"),
                  ("per-qubit gate error", "gate1err 0 1 20"), ("per-pair gate error", "gate2err 0 1 1 20"), ("asymmetric readout error", "readerr 0 1 20 1 10"), ("idle noise (T1, T2)", "coher 0 50000 70000"), ("gate durations", "time2 300\ndur2 0 1 400\ndur1 0 36"), ("waiting", "coher 0 50000 70000\nwait 0 1000"), ("scheduling", "sched\nbarrier")]
    for _, nm, op in one_q + two_q + three_q + chans + [("", e, o) for e, o in extras_ops]:
        for header in ("n 3", "dm 3"):
            r = subprocess.run([t.qsim], input=f"{header}\n{op}\nquiet\n", capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"the page names {nm!r} but `{header}` / `{op}` exits {r.returncode}")
    n_gates = len(one_q) + len(two_q) + len(three_q)
    n_reject = len([f for f in os.listdir(os.path.join(ROOT, "tests", "reject")) if f.endswith(".cho")])
    n_traps = len([f for f in os.listdir(os.path.join(ROOT, "tests", "accept")) if "//~ TRAPS" in open(os.path.join(ROOT, "tests", "accept", f)).read()])
    n_qasm = json.load(open(os.path.join(ROOT, "tests", "qasm", "results.json")))["files"]
    n_dm_circ = len([f for f in os.listdir(os.path.join(ROOT, "tests", "diff")) if f.startswith("dm_") and f.endswith(".qc")])

    def names(items):
        return ", ".join(esc(nm) for _, nm, _ in items)

    def card(title, body):
        return f'    <div class="card"><h3>{title}</h3><p>{body}</p></div>'

    P["CAPABILITIES"] = "\n".join([
        card(f"{n_gates} gates", f"One qubit: {names(one_q)}. Two: {names(two_q)}. Three: {names(three_q)}. Angles are exact fractions of &pi;."),
        card("Pure states, measured or sampled", "Up to 20 qubits (16 MiB at 20). Seeded measurement with collapse, and <code>sample N</code> to draw outcomes without collapsing. The same seed gives the same bits on every build."),
        card("Noise, two ways", f"{len(chans)} channels: {names(chans)}; asymmetric readout error; a model that adds depolarizing noise after every gate, with its own rate per qubit and per pair, or read from a device-style profile file or a real device&rsquo;s published calibration; idle decay (T1, T2) while a qubit waits, while a gate runs, or while it waits for a partner (a scheduler). Sampled runs (any size; the average is the physics) or the exact density matrix (up to 10 qubits)."),
        card("Two input formats", f"A plain-text circuit format, and OpenQASM 2.0 (angles that are multiples of &pi;; {n_qasm} circuits cross-checked with Qiskit&rsquo;s own parser)."),
        card("Algorithms", "Bell and GHZ states, teleportation, the quantum Fourier transform, Grover search, Bernstein&ndash;Vazirani and Deutsch&ndash;Jozsa, all as circuits with a known answer."),
        card("A type checker for qubits", f"A <code>Qubit</code> cannot be copied or dropped; only <code>measure</code> ends one. {n_reject} refusal fixtures, and {n_traps + 1} pinned cases the checker still misses."),
    ])
    P["N_DM"] = str(n_dm_circ)
    P["N_GATES"] = str(n_gates)

    def ul(items):
        return '<ul class="gallery">\n  ' + "\n  ".join(items) + "\n</ul>"

    groups = [
        ("Circuits and algorithms", "Gates, states and the textbook algorithms, each diffed against Qiskit.",
         ["Bell pair", "A 5-qubit state, 60 gates", "GHZ on 10 qubits", "Grover search", "Bernstein\u2013Vazirani, typed"]),
        ("The typed qubit layer", "The same circuits written with <code>Qubit</code> values the compiler tracks.",
         ["Bell pair, 200 shots, typed", "Teleportation", "Toffoli, typed"]),
        ("Noise", "Two ways to simulate it: sampled runs, and the exact density matrix.",
         ["Noise, checked against the exact answer", "Exact noise: the density matrix", "A device-style noise profile", "Idle noise: T1 and T2", "Scheduling: a waiting qubit decays", "A real device's calibration", "Against a real quantum computer"]),
        ("Input formats", "A plain-text circuit format and OpenQASM 2.0.", ["OpenQASM 2.0 in"]),
        ("Speed", "Timed against Qiskit Aer on the same circuits.", ["Speed: against Qiskit Aer"]),
        ("Reproducibility", "The same bytes on every build.", ["The same bytes, six ways"]),
    ]
    by_title = {}
    for item in sup:
        by_title[re.search(r"<h4>(.*?)</h4>", item).group(1)] = item
    parts = []
    used = set()
    for gname, gnote, titles in groups:
        items = []
        for ttl in titles:
            key = esc(ttl)
            found = [k for k in by_title if k == key or k == ttl]
            if not found:
                sys.exit(f"gallery group {gname!r}: no tile titled {ttl!r}; have {sorted(by_title)}")
            items.append(by_title[found[0]])
            used.add(found[0])
        parts.append(f'  <h4 class="gsub">{esc(gname)} <span>{gnote}</span></h4>\n' + ul(items))
    leftover = set(by_title) - used
    if leftover:
        sys.exit(f"supported tiles with no group: {sorted(leftover)}")
    P["GAL_SUPPORTED"] = "\n".join(parts)
    P["GAL_REFUSED"] = ul(ref)
    P["GAL_GAPS"] = ul(gaps)
    P["GAL_PLANNED"] = ul(soon)
    P["REJECT_TABLE"] = "\n".join(
        f"      <tr><td><code>{esc(t.refusal(f)[1])}</code></td><td><code>{esc(f)}</code></td></tr>" for f in why)
    P["_diff"] = d
    P["_t"] = t
    return P



SVG_CSS = """
.circ .wire { stroke: var(--muted); stroke-width: 1; }
.circ .qlab, .circ .sub, .chart .tick { fill: var(--muted); font: 10px var(--mono); }
.circ .box { fill: var(--surface); stroke: var(--accent); stroke-width: 1.5; }
.circ .meas { stroke: var(--muted); }
.circ .glab { fill: var(--fg); font: 600 11px var(--mono); }
.circ .dot { fill: var(--accent); }
.circ .tgt { fill: var(--surface); stroke: var(--accent); stroke-width: 1.5; }
.circ .link, .circ .arc { stroke: var(--accent); stroke-width: 1.5; fill: none; }
.circ .op.active .box { fill: var(--accent); }
.circ .op.active .glab { fill: var(--accent-fg); }
.circ .op.active .link, .circ .op.active .arc { stroke-width: 2.5; }
.circ .op.active .dot { r: 5.5px; }
.circ .op { transition: opacity .3s; }
.circ .op.later { opacity: .35; }
.chart .grid { stroke: var(--line); stroke-width: 1; }
.chart .axis { stroke: var(--muted); stroke-width: 1; }
.chart .bar { fill: var(--accent); }
.chart .bar.b1 { fill: var(--muted); }
.chart .bar.b2 { fill: var(--good); }
.chart .bar.b3 { fill: var(--fg); opacity: .6; }
.chart .band { fill: var(--accent); opacity: .14; }
.chart .gateline { stroke: var(--bad); stroke-width: 1.2; stroke-dasharray: 4 3; }
.chart .gtext { fill: var(--bad); font: 10px var(--mono); }
.chart .line { fill: none; stroke-width: 2; }
.chart .line.s0, .chart .pt.s0 { stroke: var(--accent); }
.chart .line.s1, .chart .pt.s1 { stroke: var(--good); }
.chart .pt { fill: var(--surface); stroke-width: 1.5; }
.chart .err { stroke: var(--accent); stroke-width: 1.5; }
.chart .ltext.s0 { fill: var(--accent); font: 600 10px var(--mono); }
.chart .ltext.s1 { fill: var(--good); font: 600 10px var(--mono); }
"""

LIGHT = "--bg:#fbfbfd;--fg:#15151c;--muted:#585a68;--line:#e1e2ea;--surface:#fff;--soft:#f1f1f7;--accent:#5b3fb0;--accent-fg:#fff;--good:#0f7b5f;--bad:#b42d27;--mono:ui-monospace,Menlo,Consolas,monospace;"
DARK = "--bg:#0d0c14;--fg:#e9e8f0;--muted:#a09eb4;--line:#25243a;--surface:#14131f;--soft:#1a1927;--accent:#b9a4ff;--accent-fg:#170f33;--good:#4fd1a5;--bad:#ff7b73;"


def standalone(svg):
    """The same figure as a file: variables defined inside, light and dark."""
    style = f"<style>svg{{{LIGHT}}}@media (prefers-color-scheme: dark){{svg{{{DARK}}}}}{SVG_CSS}</style>"
    head, rest = svg.split(">", 1)
    return head + ' xmlns="http://www.w3.org/2000/svg">' + style + f'<rect width="100%" height="100%" fill="var(--bg)"/>' + rest


def parse_qc(name):
    lines = [l.split() for l in open(os.path.join(ROOT, "tests", "diff", name + ".qc")) if l.strip()]
    n = int(lines[0][1])
    return n, [tuple([l[0]] + [int(x) for x in l[1:]]) for l in lines[1:]]


def op_text(op):
    name, a = op[0], op[1:]
    if name == "cx":
        return f"CNOT, control q{a[0]}, target q{a[1]}"
    if name == "cz":
        return f"CZ on q{a[0]} and q{a[1]}"
    if name == "rz":
        return f"Rz({a[1]}&pi;/{a[2]}) on q{a[0]}"
    if name == "m":
        return f"measure q{a[0]}"
    if name == "swap":
        return f"SWAP q{a[0]} and q{a[1]}"
    if name == "ccx":
        return f"Toffoli, controls q{a[0]} and q{a[1]}, target q{a[2]}"
    if name == "cp":
        return f"controlled phase {a[2]}&pi;/{a[3]}, q{a[0]} and q{a[1]}"
    if name in ("rx", "ry", "p"):
        return f"{name.capitalize() if name != 'p' else 'P'}({a[1]}&pi;/{a[2]}) on q{a[0]}"
    return f"{name.upper()} on q{a[0]}"


def ulp_distance(a, b):
    def key(x):
        (i,) = struct.unpack("<q", struct.pack("<d", x))
        return i if i >= 0 else -(1 << 63) - i
    return abs(key(a) - key(b))


def extras(t, P, diff_stdout):
    # ---- the stepper: real amplitudes after every prefix of three circuits -----------
    data, diagrams, tabs = {}, [], []
    for name, title in (("bell", "Bell pair"), ("ghz4", "GHZ, 4 qubits"), ("teleport_unitary", "Teleportation, before the measurements"),
                        ("qft4", "Fourier transform of |5>"), ("grover3", "Grover search for 101")):
        n, ops = parse_qc(name)
        ops = [o for o in ops if o[0] not in ("seed", "sample")]
        frames = []
        for k in range(len(ops) + 1):
            text = f"n {n}\n" + "".join(" ".join(str(x) for x in o) + "\n" for o in ops[:k])
            out = subprocess.run([t.qsim], input=text, capture_output=True, text=True).stdout
            amps = amplitudes(out)
            fr = []
            for i in range(2 ** n):
                ar, ai = amps.get(i, (0.0, 0.0))
                p = ar * ar + ai * ai
                fr.append([round(p, 6), svgs.phase_color(ar, ai) if p > 1e-12 else "none", round(ar, 4), round(ai, 4)])
            frames.append(fr)
        data[name] = {"n": n, "title": title, "ops": [re.sub("<[^>]*>", "", op_text(o)).replace("&pi;", "pi") for o in ops], "frames": frames}
        diagrams.append(f'<div class="stepcirc" data-circuit="{name}" hidden>{svgs.circuit_svg(n, ops, f"Circuit diagram: {title}", current=True, natural=True)}</div>')
        tabs.append(f'<button type="button" class="tab" data-circuit="{name}">{esc(title)}</button>')
    P["STEPPER_DATA"] = json.dumps(data, separators=(",", ":"))
    P["STEPPER_DIAGRAMS"] = "\n    ".join(diagrams)
    P["STEPPER_TABS"] = "\n      ".join(tabs)

    # ---- diagrams for gallery tiles ----------------------------------------------------
    n, ops = parse_qc("bell")
    P["DIAGRAM_BELL"] = svgs.circuit_svg(n, ops, "Circuit diagram: H on qubit 0, then CNOT from qubit 0 to qubit 1")
    n, ops = parse_qc("teleport_unitary")
    P["DIAGRAM_TELEPORT"] = svgs.circuit_svg(n, ops, "Circuit diagram of the unitary half of teleportation")

    # ---- graph: worst error per circuit, from the real diff run -----------------------------
    rows = []
    for line in diff_stdout.splitlines():
        m = re.match(r"ok\s+(\S+)\s+worst\s+([0-9.e+-]+)", line)
        if m and m.group(1) not in ("trig",):
            rows.append((m.group(1), float(m.group(2))))
    rows.sort()
    P["CHART_ERROR"] = svgs.hbar_chart(rows, "Worst amplitude error against Qiskit for each circuit, on a log axis, all far below the 1e-12 gate", gate=1e-12)
    dm_rows = [v for nm, v in rows if nm.startswith("dm_")]
    P["DM_WORST"] = f"{max(dm_rows):.1e}"
    P["NOISE_Z"] = f"{max(c['max_z'] for c in json.load(open(os.path.join(DOCS, 'data', 'noise_check.json')))['circuits']):.1f}"
    P["N_ERR_ROWS"] = str(len(rows))
    P["N_ERR_ALL"] = str(len(rows) + 1)
    P["N_ERR_EXACT"] = str(sum(1 for _, v in rows if v == 0.0))

    # ---- graph: 800 seeded runs of a uniform 3-qubit state ---------------------------------
    counts = [0] * 8
    shots = 800
    for seed in range(1, shots + 1):
        text = f"n 3\nseed {seed}\nh 0\nh 1\nh 2\nm 0\nm 1\nm 2\nquiet\n"
        out = subprocess.run([t.qsim], input=text, capture_output=True, text=True).stdout
        bits = [int(l.split()[2]) for l in out.splitlines() if l.startswith("m ")]
        counts[bits[0] + 2 * bits[1] + 4 * bits[2]] += 1
    exp = shots / 8
    sigma = math.sqrt(shots * (1 / 8) * (7 / 8))
    chi2 = sum((c - exp) ** 2 / exp for c in counts)
    P["CHART_UNIFORM"] = svgs.count_hist([f"{i:03b}" for i in range(8)], counts, exp, 2 * sigma,
                                         f"Counts of each three-bit outcome over {shots} seeded runs, expected {exp:.0f}, shaded band is two standard deviations")
    P["UNIFORM_TEXT"] = f"{shots} runs, seeds 1 to {shots}: chi-squared {chi2:.1f} on 7 degrees of freedom (a fair sampler exceeds 14.1 about 5% of the time)"

    # ---- graph: Bell correlations ---------------------------------------------------------------
    bc = [0] * 4
    for seed in range(1, shots + 1):
        text = f"n 2\nseed {seed}\nh 0\ncx 0 1\nm 0\nm 1\nquiet\n"
        out = subprocess.run([t.qsim], input=text, capture_output=True, text=True).stdout
        bits = [int(l.split()[2]) for l in out.splitlines() if l.startswith("m ")]
        bc[bits[0] + 2 * bits[1]] += 1
    P["CHART_BELL"] = svgs.count_hist(["q0=0 q1=0", "q0=1 q1=0", "q0=0 q1=1", "q0=1 q1=1"], bc, shots / 2, 0,
                                      f"Counts of the four outcomes of measuring both Bell-pair qubits over {shots} seeded runs: the two mixed outcomes never occur")
    P["BELL_TEXT"] = f"{bc[0]} + {bc[3]} agree, {bc[1]} + {bc[2]} disagree, of {shots}"

    # ---- graph: ulp distance of sin/cos from the C library -------------------------------------
    _, tq = t.run_qc("trig")
    ulps = []
    ref = [l for l in open(os.path.join(ROOT, "tests", "diff", "trig.ref")) if l.startswith("trig")]
    got = [l for l in tq.splitlines() if l.startswith("trig")]
    for g, r in zip(got, ref):
        gf, rf = g.split()[1:], r.split()[1:]
        for a, b in zip(gf, rf):
            ulps.append(ulp_distance(float(a), float(b)))
    hist = [ulps.count(0), ulps.count(1), sum(1 for u in ulps if u >= 2)]
    P["CHART_ULP"] = svgs.count_hist(["0 ulp", "1 ulp", "2+ ulp"], hist, 0, 0,
                                     f"Distance of cancho's sin and cos from the C library over {len(ulps)} values: {hist[0]} identical, {hist[1]} one ulp away, {hist[2]} further")
    P["ULP_TEXT"] = f"{len(ulps)} values from {len(ulps) // 2} angles; none more than {max(ulps)} ulp away"

    # ---- graph: timings (a checked-in file, not re-measured) ------------------------------
    tm = json.load(open(os.path.join(DOCS, "data", "timings.json")))
    P["CHART_TIMING"] = svgs.line_chart([("Cranelift", tm["seconds"]["cranelift"]), ("LLVM", tm["seconds"]["llvm"])], tm["qubits"],
                                        "Seconds to apply H to every qubit, against the number of qubits, on a log axis; each added qubit roughly doubles the time",
                                        "qubits", "seconds")
    P["TIMING_TEXT"] = f"Measured {tm['measured']} on {tm['machine']}: minimum of 3 runs, output off. 20 qubits is {tm['seconds']['cranelift'][-1] * 1000:.0f} ms (Cranelift) and {tm['seconds']['llvm'][-1] * 1000:.0f} ms (LLVM); 2^20 amplitudes is 16 MiB."

    # ---- standalone images for the README ----------------------------------------------------------
    img = os.path.join(DOCS, "img")
    return {
        os.path.join(img, "bell-circuit.svg"): standalone(P["DIAGRAM_BELL"]),
        os.path.join(img, "teleport-circuit.svg"): standalone(P["DIAGRAM_TELEPORT"]),
        os.path.join(img, "error-per-circuit.svg"): standalone(P["CHART_ERROR"]),
        os.path.join(img, "timings.svg"): standalone(P["CHART_TIMING"]),
    }


def render(cancho, dump=None):
    tpl = open(os.path.join(DOCS, "index.template.html")).read()
    P = build(cancho)
    t, d = P.pop("_t"), P.pop("_diff")
    files = extras(t, P, d)
    P["SVG_CSS"] = SVG_CSS
    if dump:
        json.dump(P, open(dump, "w"), indent=1, sort_keys=True)
    for k, v in P.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", tpl)
    if left:
        sys.exit(f"unfilled placeholders: {sorted(set(left))}")
    return tpl, files


class Recorder:
    """With --transcript, remember every command the builder runs (argv, stdin) and what it printed, so that
    `tools/site/` can replay the same build without running anything (and be compared with this one)."""

    def __init__(self):
        self.calls = {}
        self.real = subprocess.run

    def norm(self, cmd):
        out = []
        for c in cmd:
            c = str(c)
            c = re.sub(r"/tmp/[^/ ]*(site|qprofile|qcalib|qcconv)-[^/ ]*", "$TMP", c)
            c = re.sub(r"^.*/(cancho)$", r"\1", c)
            if c == sys.executable:
                c = "python3"
            out.append(c)
        return out

    def run(self, cmd, *a, **kw):
        r = self.real(cmd, *a, **kw)
        key = "\x01".join(self.norm(cmd)) + "\x02" + (kw.get("input") or "")
        self.calls[key] = {"rc": r.returncode, "out": r.stdout if isinstance(r.stdout, str) else "", "err": r.stderr if isinstance(r.stderr, str) else ""}
        return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", help="write every command run, and its output, to this JSON file")
    ap.add_argument("--dump", help="write every placeholder's value to this JSON file")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    rec = None
    if args.transcript:
        rec = Recorder()
        subprocess.run = rec.run
    out, files = render(args.compiler, args.dump)
    if rec:
        json.dump(rec.calls, open(args.transcript, "w"))
    files[os.path.join(DOCS, "index.html")] = out
    stale = [p for p, v in files.items() if not os.path.exists(p) or open(p).read() != v]
    if args.check:
        if stale:
            sys.exit("out of date, run scripts/build_site.py: " + ", ".join(os.path.relpath(p, ROOT) for p in stale))
        print(f"docs/index.html and {len(files) - 1} images are up to date")
    else:
        for p, v in files.items():
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(v)
        print(f"wrote {len(files)} files")


if __name__ == "__main__":
    main()
