"""The random mirror circuits of the gate-rate regression (docs/rates-regression.md): one generator for the simulated test (`rates_sim.py`) and for the device (`hw_spike.py --set rates`)."""

LAYER_P = 0.7      # the chance that a qubit gets a gate in a layer: without this every qubit has the same count of one-qubit gates in every circuit and their rates cannot be told apart


def circuit(rnd, n, layers, cz_probability=0.6):
    """(forward ops, one-qubit gate count per qubit, `cz` count per neighbouring pair) of a random circuit of `layers` layers: on a random part of the
    qubits an `sx` (twice as often) or an `x`, then `cz` on random disjoint neighbouring pairs. An op is (name, a, b)."""
    ops, n1, n2 = [], [0] * n, [0] * (n - 1)
    for _ in range(layers):
        for q in range(n):
            if rnd.random() < LAYER_P:
                g = rnd.choice(["sx", "sx", "x"])
                ops.append((g, q, 0))
                n1[q] += 1
        used = set()
        for p in range(n - 1):
            if rnd.random() < cz_probability and p not in used and p + 1 not in used:
                ops.append(("cz", p, p + 1))
                used |= {p, p + 1}
                n2[p] += 1
    return ops, n1, n2


def inverse(ops):
    """sx^-1 is rx(-pi/2) (`sx_inv`); x and cz are their own inverses."""
    return [("sx_inv" if g == "sx" else g, a, b) for g, a, b in reversed(ops)]


def design(rnd, n, count, oneq=True):
    """`count` circuits as (ops incl. the inverse, n1, n2) with every gate counted twice (forward and back). Every third circuit has one-qubit gates only
    (10 to 60 layers) when `oneq`, so that their small rates show above the noise."""
    out = []
    for i in range(count):
        if oneq and i % 3 == 0:
            fwd, n1, n2 = circuit(rnd, n, rnd.randint(10, 60), 0.0)
        else:
            fwd, n1, n2 = circuit(rnd, n, rnd.randint(1, 12))
        out.append((fwd + inverse(fwd), [2 * c for c in n1], [2 * c for c in n2]))
    return out


def qiskit_circuit(ops, n):
    """The ops as a Qiskit circuit, a barrier between the circuit and its inverse (so that nothing cancels), measured into one register."""
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(n)
    half = len(ops) // 2
    for k, (g, a, b) in enumerate(ops):
        if k == half:
            qc.barrier()
        if g == "sx":
            qc.sx(a)
        elif g == "sx_inv":
            qc.sxdg(a)
        elif g == "x":
            qc.x(a)
        else:
            qc.cz(a, b)
    qc.measure_all()
    return qc
