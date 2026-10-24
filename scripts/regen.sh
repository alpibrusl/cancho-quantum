#!/bin/sh
# Regenerate the compiled circuits (tests/circuits) and the OpenQASM files (tests/qasm) from tests/diff/*.qc
# with the cancho tool tools/qcconv.cho. `scripts/gen_reference.py` (Qiskit) writes tests/diff itself.
#
#     CANCHO=path/to/cancho sh scripts/regen.sh
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-cancho}
tmp=$(mktemp -d)
"$CANCHO" build tools/qcconv.cho --std -o "$tmp/qcconv"
mkdir -p tests/circuits tests/qasm
circuits=0
qasm=0
for f in tests/diff/*.qc; do
    name=$(basename "$f" .qc)
    if { echo "cho $name"; cat "$f"; } | "$tmp/qcconv" > "$tmp/out.cho" 2>/dev/null; then
        mv "$tmp/out.cho" "tests/circuits/$name.cho"
        circuits=$((circuits + 1))
    fi
    if { echo qasm; cat "$f"; } | "$tmp/qcconv" > "$tmp/out.qasm" 2>/dev/null; then
        mv "$tmp/out.qasm" "tests/qasm/$name.qasm"
        qasm=$((qasm + 1))
    fi
done
"$CANCHO" fmt tests/circuits > /dev/null
echo "wrote $circuits compiled circuits and $qasm QASM files"
rm -rf "$tmp"
