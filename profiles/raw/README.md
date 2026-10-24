# Raw calibration snapshots

`ibm_perth_props_2024-05-27.json` is IBM's published backend-properties snapshot of the 7-qubit
`ibm_perth` (last update 2024-05-27), copied unchanged from the `props_perth.json` that
ships in the `qiskit-ibm-runtime` package (Apache-2.0, IBM) as its `FakePerth` backend. This project did
not measure anything. `qcalib` turns it into `../ibm_perth_2024-05-27.json`:

    cancho build tools/qcalib.cho --std -o qcalib
    ./qcalib < profiles/raw/ibm_perth_props_2024-05-27.json > profiles/ibm_perth_2024-05-27.json
