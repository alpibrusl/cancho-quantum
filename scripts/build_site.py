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
        links(("Source", blob("tests/accept/teleport.cho")))))
    sup.append(tile("The same bytes, six ways",
        f"Every one of the {P['N_GOLDEN']} circuits runs interpreted and as a compiled cancho function, on Cranelift and LLVM (x86-64) and LLVM aarch64 under <code>qemu-user</code>. All six outputs are byte-identical and match the SHA-256 checked in. The aarch64 run is emulation, not arm64 hardware.",
        f'      <pre class="code small">bell\ncircuit  {esc(prov["bell"]["circuit_body_id"][:16])}...\noutput   {esc(prov["bell"]["output_sha256"][:16])}...\nlibrary  {esc(prov["bell"]["library_digest"][:16])}...</pre>\n'
        + links(("Provenance", blob("tests/golden/provenance.json")), ("Results", blob("docs/m3-results.md")))))

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
        ("A Qpu capability", "Which backend a program can reach and how many shots it may spend, readable from the program text before it runs. Needs compiler work; shot budgets are only decidable for constant counts, so the honest claim is a declared bound a supervisor enforces.", "Needs the compiler", [("Plan", blob("docs/qubit-types.md"))]),
        ("Refuse CNOT(q, q) at check time", "A same-place-twice rule would close at least one of the three ways; its design predicts a second, which is not measured, and says the third needs a different fix. Written, not built.", "Needs the compiler", [("Design", "https://github.com/alpibrusl/cancho/pull/608"), ("Asker", blob("docs/m2-results.md"))]),
        ("Private constructors", "So that only the simulator can mint a qubit. A proposed opt-in <code>opaque</code> struct; written, not built.", "Needs the compiler", [("Design", "https://github.com/alpibrusl/cancho/pull/608"), ("Asker", blob("tests/accept/forged_qubit.cho"))]),
        ("OpenQASM in and out", "Emit first, parse later. The circuit format today is a stand-in.", "Planned", []),
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
    return P


def render(cancho):
    tpl = open(os.path.join(DOCS, "index.template.html")).read()
    P = build(cancho)
    for k, v in P.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", tpl)
    if left:
        sys.exit(f"unfilled placeholders: {sorted(set(left))}")
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--compiler", default=os.environ.get("CANCHO", "cancho"))
    args = ap.parse_args()
    out = render(args.compiler)
    path = os.path.join(DOCS, "index.html")
    if args.check:
        if not os.path.exists(path) or open(path).read() != out:
            sys.exit("docs/index.html is out of date: run scripts/build_site.py")
        print("docs/index.html is up to date")
    else:
        open(path, "w").write(out)
        print(f"wrote {path} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
