Install cancho-quantum and try it on one small circuit. Work in a new empty directory, keep every path free of spaces, and never use sudo. Run steps 2 to 5 in one shell session. Report honestly; do not retry a failing command in a loop and do not edit the repository to make a command pass.

1. Check that `git`, `cargo` (Rust, via rustup), `python3` and a C linker (`cc`) exist. If one is missing, stop and tell me which; do not install system packages on your own.

2. Get the cancho compiler at the revision this project was measured against, and build it:
   git clone https://github.com/alpibrusl/cancho.git
   git -C cancho checkout 3fa3fbb
   (cd cancho && cargo build -p cancho)
   export CANCHO="$PWD/cancho/target/debug/cancho"

3. Get the simulator:
   git clone https://github.com/alpibrusl/cancho-quantum.git
   cd cancho-quantum

4. Run the checks that need no network after the clone:
   python3 scripts/check_types.py          # every line must say ok; ends "23 of 23 fixtures behave as stated"
   Then, only if you may install Python packages into a virtual environment (python3 -m venv .venv && . .venv/bin/activate && pip install qiskit numpy):
   python3 scripts/check_diff.py           # amplitudes against Qiskit; ends with the worst error, which must be under 1e-12
   python3 scripts/check_qasm.py           # OpenQASM files read by Qiskit's parser and by qsim agree
   python3 scripts/check_noise.py          # noisy runs averaged over 4000 seeds match an exact density-matrix calculation (about 40 s)
   python3 scripts/check_determinism.py    # six builds per circuit must give identical bytes (omit --arm64 unless qemu-aarch64 is installed)

5. Try the simulator and the checker on your own input:
   $CANCHO build src/*.cho --std -o qsim
   printf 'n 2\nh 0\ncx 0 1\n' | ./qsim     # a Bell state: amp 0 and amp 3 are 7.071067811865475e-1
   cat tests/qasm/qft4.qasm | ./qsim | head -3   # the same simulator reading OpenQASM 2.0
   printf 'n 3\nh 0\nh 1\nh 2\nseed 1\nsample 100\n' | ./qsim | head -8   # 100 samples, counts per outcome
   Now make a program that clones a qubit and watch it be refused. Copy tests/reject/clone_qubit.cho, read it, and run:
   $CANCHO check src/complex.cho src/state.cho src/gates.cho src/measure.cho src/noise.cho src/qubit.cho tests/reject/clone_qubit.cho --std ; echo "exit $?"           # expect exit 1
   $CANCHO check src/complex.cho src/state.cho src/gates.cho src/measure.cho src/noise.cho src/qubit.cho tests/reject/clone_qubit.cho --std --output json          # the rule is "linear-use-after-move"
   Do not fix the refusal by copying the qubit: it cannot be copied. A qubit is ended by `qubit.measure`.
   Then run tests/accept/same_handle_cx.cho (see its header) and report what happened: it compiles and then stops at run time. That is a known gap, not a bug in your setup.

6. Tell me, briefly:
   - the exit code and the first line each command printed in step 5;
   - whether step 4's checks passed, and the last line each printed;
   - anything that failed, with the exact error.
Docs: README.md (the commands), docs/qubit-types.md (the design and what the checker cannot say), docs/m2-results.md (what was refused and what was not), docs/m3-results.md (determinism).
