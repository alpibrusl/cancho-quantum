#!/usr/bin/env python3
"""Offline test of the pre-flight in `hw_spike.py`: no account, no device.

    python3 scripts/check_hw_spike.py

A fake device (Aer with `FakePerth`'s noise) is given two broken qubits, one that always reads 1 and one that always reads 0,
as `ibm_kingston`'s qubit 0 did on 2026-10-26, and `scan` has to name exactly those two and none of the healthy ones. The
classifier's thresholds are checked at their edges.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hw_spike as hw  # noqa: E402


def main():
    from qiskit_aer.noise import NoiseModel, ReadoutError
    from qiskit_ibm_runtime import fake_provider

    assert hw.classify(0.0, 0.0) == "ok" and hw.classify(0.05, 0.0) == "ok" and hw.classify(0.0, 0.051) == "weak"
    assert hw.classify(0.15, 0.0) == "weak" and hw.classify(0.1501, 0.0) == "bad" and hw.classify(0.0, 0.9) == "bad"

    backend = fake_provider.FakePerth()
    model = NoiseModel.from_backend(backend)
    model.add_readout_error(ReadoutError([[0, 1], [0, 1]]), [0])   # qubit 0: always reads 1
    model.add_readout_error(ReadoutError([[1, 0], [1, 0]]), [3])   # qubit 3: always reads 0

    # `scan` builds its own simulator from the backend's noise; swap the model in
    orig = NoiseModel.from_backend
    NoiseModel.from_backend = staticmethod(lambda b, **kw: model)
    try:
        result = hw.scan(backend, list(range(backend.num_qubits)), 1000, stand_in=True)
    finally:
        NoiseModel.from_backend = orig
    bad, weak = hw.report_scan(result)
    assert bad == [0, 3], (bad, weak)
    assert result[0][0] > 0.99 and result[3][1] > 0.99
    assert 0 not in weak and 3 not in weak
    print("ok   the pre-flight names the qubit stuck at 1 and the one stuck at 0, and no healthy one")


if __name__ == "__main__":
    main()
