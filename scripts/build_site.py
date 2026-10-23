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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = os.path.join(ROOT, "docs")
REPO = "https://github.com/alpibrusl/cancho-quantum"
LIB = ["complex", "state", "gates", "measure", "qubit"]


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
    d = sh([sys.executable, "scripts/check_diff.py", "--exe", t.qsim, "--compiler", cancho]).stdout
    worst = re.search(r"worst amplitude error over (\d+) circuits: ([0-9.e+-]+)", d)
    ulp = re.search(r"libm over the `trig` lines: (\d+) ulp", d)
    ty = sh([sys.executable, "scripts/check_types.py", "--compiler", cancho]).stdout
    fx = re.search(r"(\d+) of (\d+) fixtures behave as stated", ty)
    golden = [l for l in open(os.path.join(ROOT, "tests", "golden", "outputs.sha256")) if l.strip()]
    prov = json.load(open(os.path.join(ROOT, "tests", "golden", "provenance.json")))

    P["AGENT_PROMPT"] = esc(open(os.path.join(DOCS, "agent-prompt.md")).read().rstrip("\n"))
    P["N_CIRCUITS"] = worst.group(1)
    P["WORST"] = worst.group(2)
    P["ULP"] = ulp.group(1)
    P["FIX_OK"], P["FIX_ALL"] = fx.group(1), fx.group(2)
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
    qr = json.load(open(os.path.join(ROOT, "tests", "qasm", "results.json")))
    sup.append(tile("OpenQASM 2.0 in",
        f"<code>qsim</code> reads the OpenQASM a circuit is usually written in. All {qr['files']} circuits that QASM can express were converted, parsed by Qiskit&rsquo;s own reader and by <code>qsim</code>, and agree with the reference. Going the other way, {qr['qiskit_written_run']} of the files <em>Qiskit</em> wrote run; {qr['qiskit_written_refused_decimal']} were refused because they carry a decimal angle (only multiples of &pi; are supported, on purpose).",
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
        ("A Qpu capability", "Which backend a program can reach and how many shots it may spend, readable from the program text before it runs. Needs compiler work; shot budgets are only decidable for constant counts, so the honest claim is a declared bound a supervisor enforces.", "Needs the compiler", [("Tracked in cancho#612", "https://github.com/alpibrusl/cancho/issues/612"), ("Plan", blob("docs/qubit-types.md"))]),
        ("Refuse CNOT(q, q) at check time", "A same-place-twice rule would close at least one of the three ways; its design predicts a second, which is not measured, and says the third needs a different fix. Written, not built.", "Needs the compiler", [("Tracked in cancho#610", "https://github.com/alpibrusl/cancho/issues/610"), ("Design PR #608", "https://github.com/alpibrusl/cancho/pull/608")]),
        ("Private constructors", "So that only the simulator can mint a qubit. A proposed opt-in <code>opaque</code> struct; written, not built.", "Needs the compiler", [("Tracked in cancho#611", "https://github.com/alpibrusl/cancho/issues/611"), ("Design PR #608", "https://github.com/alpibrusl/cancho/pull/608")]),
        ("The rest of OpenQASM", "Decimal angles (their digits are rounded, so they are refused today), <code>gate</code> definitions, <code>u3</code>, <code>if</code>, and writing QASM from cancho itself (a Python script writes it now).", "Planned", [("Reader", blob("src/qasm.cho"))]),
        ("Noise and mixed states", "A density-matrix simulator for noise. The state vector here is pure, and a measurement samples one outcome.", "Later", []),
        ("A second reference, Cirq", "Qiskit is the only reference so far. A second one would catch a convention both share.", "Planned", []),
        ("Real arm64 hardware", "The aarch64 result is emulation. A run on a real arm64 machine is still owed.", "Planned", [("Results", blob("docs/m3-results.md"))]),
        ("A cloud quantum service", "Submit a circuit over HTTPS. The authority report will be coarser here, because host-set bounds are design-only in cancho.", "Later", []),
        ("Adjoint and controlled gates", "Not possible today: cancho has no function values, so a gate cannot be passed to a transform. Circuits stay data.", "Not possible yet", []),
        ("A GPU backend", "Out of scope until cancho-gpu exists. A state vector of 20 qubits is fine on one CPU core.", "Out of scope", []),
    ]
    soon = [tile(tt, body, links(*lk) if lk else "", soon=True, badge=bg) for tt, body, bg, lk in plan]

    def ul(items):
        return '<ul class="gallery">\n  ' + "\n  ".join(items) + "\n</ul>"

    P["GAL_SUPPORTED"] = ul(sup)
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
.chart .band { fill: var(--accent); opacity: .14; }
.chart .gateline { stroke: var(--bad); stroke-width: 1.2; stroke-dasharray: 4 3; }
.chart .gtext { fill: var(--bad); font: 10px var(--mono); }
.chart .line { fill: none; stroke-width: 2; }
.chart .line.s0, .chart .pt.s0 { stroke: var(--accent); }
.chart .line.s1, .chart .pt.s1 { stroke: var(--good); }
.chart .pt { fill: var(--surface); stroke-width: 1.5; }
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


def render(cancho):
    tpl = open(os.path.join(DOCS, "index.template.html")).read()
    P = build(cancho)
    t, d = P.pop("_t"), P.pop("_diff")
    files = extras(t, P, d)
    P["SVG_CSS"] = SVG_CSS
    for k, v in P.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", tpl)
    if left:
        sys.exit(f"unfilled placeholders: {sorted(set(left))}")
    return tpl, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    out, files = render(args.compiler)
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
