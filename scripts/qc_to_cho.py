#!/usr/bin/env python3
"""Turn each tests/diff/<name>.qc into a compiled circuit, tests/circuits/<name>.cho.

    python3 scripts/qc_to_cho.py

`qsim` interprets a circuit read from stdin. This writes the same circuit
as a cancho *function*, so that it can be compiled, run, and given a
content identity by `cancho ids`: the `body circuit` line is the hash of
the circuit as code. Each file also holds the small driver (`run`,
`main`) that prints what `qsim` prints, and `scripts/check_determinism.py`
requires the two to agree byte for byte.

Generated files say so at the top; edit the .qc and regenerate. Run
`cancho fmt tests/circuits` afterwards: the repository keeps them formatted.
"""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DIFF = os.path.join(ROOT, "tests", "diff")
OUT = os.path.join(ROOT, "tests", "circuits")

DRIVER = '''
fn run[&h, &i](heap: &!h Heap, io: &!i Io) -> [heap, io_write] int {
    let amp = box_slice(heap, state.floats_for(%(n)d), 0.0);
    region r {
        let rng = alloc_slice[r](profile.size(), 0);
        profile.init(rng, 88172645463325252);
        let scratch = alloc_slice[r](24, byte_of(0));
        borrow mut amp as &!w in {
            let st = contents(w);
            state.start(st);
            circuit(%(args)s);
            dump.amplitudes(io, st, %(n)d, scratch);
        }
    }
    unbox_slice(heap, amp);
    return 0;
}

fn main(world: World) -> [] int {
    let Split { io, ffi, fs, heap, args } = split(world);
    release(ffi);
    release(fs);
    release(args);
    var status = 0;
    borrow mut heap as &!h in {
        borrow mut io as &!i in {
            status = run(h, i);
        }
    }
    release(heap);
    release(io);
    return status;
}
'''


def convert(name):
    lines = [l.split() for l in open(os.path.join(DIFF, name + ".qc")) if l.strip()]
    if lines[0][0] != "n":
        return None          # a `dm <n>` circuit: the density-matrix mode has no compiled form
    n = int(lines[0][1])
    body, prints = [], False
    # The noise parameters live in the sampler's slice, exactly as when `qsim` interprets the
    # circuit, so a compiled circuit calls the same functions. The after-gate calls are emitted only
    # for a circuit that sets a gate-noise parameter somewhere.
    gate_noise = any(l[0] in ("model1", "model2", "gate1err", "gate2err", "time1", "time2", "dur1", "dur2", "sched") for l in lines[1:])

    for op in lines[1:]:
        k, a = op[0], [int(x) for x in op[1:]]
        if gate_noise and k in ("cx", "cz", "cp", "swap"):
            body.append(f"noise.before2(st, {n}, {a[0]}, {a[1]}, rng);")
        if k == "sample":
            body.append(f"noise.barrier(st, {n}, rng);")
        if k in ("h", "x", "y", "z", "s", "t", "sdg", "tdg"):
            body.append(f"gates.{k}(st, {n}, {a[0]});")
        elif k in ("cx", "cz"):
            body.append(f"gates.{k}(st, {n}, {a[0]}, {a[1]});")
        elif k == "rz":
            body.append(f"gates.rz(st, {n}, {a[0]}, gates.angle({a[1]}, {a[2]}));")
        elif k == "swap":
            body.append(f"gates.swap(st, {n}, {a[0]}, {a[1]});")
        elif k == "ccx":
            body.append(f"gates.ccx(st, {n}, {a[0]}, {a[1]}, {a[2]});")
        elif k in ("rx", "ry", "p"):
            body.append(f"gates.{k}(st, {n}, {a[0]}, gates.angle({a[1]}, {a[2]}));")
        elif k == "cp":
            body.append(f"gates.cp(st, {n}, {a[0]}, {a[1]}, gates.angle({a[2]}, {a[3]}));")
        elif k in ("bitflip", "phaseflip", "depol", "ampdamp"):
            body.append(f"noise.{k}(st, {n}, {a[0]}, noise.prob({a[1]}, {a[2]}), rng);")
        elif k == "sample":
            prints = True
            body.append(f"dump.samples(io, st, {n}, rng, {a[0]});")
        elif k == "seed":
            body.append(f"rng[0] = {a[0]};")
        elif k == "m":
            prints = True
            body.append(f"dump.measurement(io, {a[0]}, noise.readout(measure.measure(st, {n}, {a[0]}, rng), {a[0]}, rng));")
        elif k == "depol2":
            body.append(f"noise.depol2(st, {n}, {a[0]}, {a[1]}, noise.prob({a[2]}, {a[3]}), rng);")
        elif k in ("readout", "model1", "model2"):
            body.append(f"profile.set_slot(rng, {({'readout': 2, 'model1': 4, 'model2': 6})[k]}, {a[0]}, {a[1]});")
        elif k == "gate1err":
            body.append(f"profile.set_g1(rng, {a[0]}, {a[1]}, {a[2]});")
        elif k == "gate2err":
            body.append(f"profile.set_g2(rng, {a[0]}, {a[1]}, {a[2]}, {a[3]});")
        elif k == "readerr":
            body.append(f"profile.set_ro(rng, {a[0]}, {a[1]}, {a[2]}, {a[3]}, {a[4]});")
        elif k == "coher":
            body.append(f"profile.set_coh(rng, {a[0]}, {a[1]}, {a[2]});")
        elif k in ("time1", "time2"):
            body.append(f"profile.set_time(rng, {968 if k == 'time1' else 969}, {a[0]});")
        elif k == "dur1":
            body.append(f"profile.set_dur1(rng, {a[0]}, {a[1]});")
        elif k == "dur2":
            body.append(f"profile.set_dur2(rng, {a[0]}, {a[1]}, {a[2]});")
        elif k == "wait":
            body.append(f"noise.relax(st, {n}, {a[0]}, {a[1]}, rng);")
            body.append(f"profile.set_clock(rng, {a[0]}, profile.clock(rng, {a[0]}) + {a[1]});")
        elif k == "sched":
            body.append("rng[1410] = 1;")
        elif k == "barrier":
            body.append(f"noise.barrier(st, {n}, rng);")
        elif k == "trig":
            prints = True
            body.append(f"dump.trig(io, scratch, {a[0]}, {a[1]});")
        else:
            raise ValueError(k)
        if gate_noise and k in ("h", "x", "y", "z", "s", "t", "sdg", "tdg", "rx", "ry", "rz", "p"):
            body.append(f"noise.after1(st, {n}, {a[0]}, rng);")
        if gate_noise and k in ("cx", "cz", "cp", "swap"):
            body.append(f"noise.after2(st, {n}, {a[0]}, {a[1]}, rng);")
    row = "[io_write]" if prints else "[]"
    out = [
        f"// Generated by scripts/qc_to_cho.py from tests/diff/{name}.qc. Do not edit.",
        "",
        "import qc.dump;",
        "import qc.gates;",
        "import qc.measure;",
        "import qc.noise;",
        "import qc.profile;",
        "import qc.state;",
        "import std.io;",
        "",
        "// The circuit. `cancho ids` gives this function's body its identity.",
        f"fn circuit[&i, &s, &r, &b](io: &!i Io, st: &!s [float], rng: &!r [int], scratch: &!b [byte]) -> {row} int {{",
    ]
    out += ["    " + b for b in body]
    out += [f"    noise.barrier(st, {n}, rng);"] if gate_noise else []
    out += ["    return 0;", "}"]
    text = "\n".join(out) + "\n" + DRIVER % {"n": n, "args": "io, st, rng, scratch"}
    return text


def main():
    os.makedirs(OUT, exist_ok=True)
    names = sorted(f[:-3] for f in os.listdir(DIFF) if f.endswith(".qc"))
    wrote = 0
    for name in names:
        text = convert(name)
        if text is not None:
            open(os.path.join(OUT, name + ".cho"), "w").write(text)
            wrote += 1
    print(f"wrote {wrote} circuits to {OUT}")


if __name__ == "__main__":
    main()
