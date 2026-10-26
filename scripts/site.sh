#!/bin/sh
# Build the landing page (docs/index.html and its images) with the cancho tool tools/site, which runs the compiler, qsim,
# qprofile and the accept fixtures itself. `scripts/build_site.py` is the reference it is checked against
# (`scripts/check_site.py`). Extra arguments go to the tool: `--check` fails if the files are out of date instead of writing them.
#
#     CANCHO=path/to/cancho sh scripts/site.sh [--check]
set -eu
cd "$(dirname "$0")/.."
CANCHO=${CANCHO:-cancho}
tmp=$(mktemp -d)
files=""
for m in numfmt text svg facts files replay util live page1 page2 page3 page4 page5 page6 page7 page8 page9 page10 assemble site; do
    files="$files tools/site/$m.cho"
done
"$CANCHO" build $files --std -o "$tmp/site"
"$tmp/site" --live --compiler "$CANCHO" --tmp "$tmp/x-" "$@"
rm -rf "$tmp"
