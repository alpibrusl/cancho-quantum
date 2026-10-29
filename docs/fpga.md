# qsim on an FPGA: a shot counter and a pulse sequencer

Written 2026-10-29. Answers issue #32. Everything here ran on a Sipeed Tang Nano 20K (Gowin GW2AR-18) with the design `lab` of
[cancho-hdl](https://github.com/alpibrusl/cancho-hdl) (`boards/tang-nano-20k/rtl/lab.v`, contract `lab/lab.chw`; see that repository's
`docs/fpga-experiments.md`). The two tools here are cancho, use the `Tty` capability under `/dev` and no foreign call
(`cancho authority`: `tty_open("/dev")`, `tty_read`, `tty_write`, `poll`, `io_write`, `io_read`, `heap`). `tools/fpga/labio.cho` is a copy
of cancho-hdl's `boards/tang-nano-20k/host/labio.cho`.

**This is not about speed.** `qsim` on a CPU is far faster than a 27 MHz part behind a 115200 baud serial line, and nothing here changes
that. It is about exact integer counting, and about timing a CPU cannot do.

## 1. `tools/fpga/hist.cho`: the board counts qsim's samples

```sh
cancho build tools/fpga/labio.cho tools/fpga/hist.cho --std -o fpga-hist
printf 'n 3\nh 0\ncx 0 1\ncx 1 2\nseed 7\nsample 1000\n' | qsim | grep ^sample | ./fpga-hist
```

`qsim` prints `sample <bits> <count>` per distinct outcome (`src/dump.cho`), not the shots in order, so the tool sends the board `<count>`
shots of each outcome and then reads all bins back. **Measured:** GHZ on 3 qubits, 1000 shots: bins 000 = 498, 111 = 502, equal to qsim's;
5 qubits in uniform superposition, 4000 shots, 32 outcomes: all equal; total counted equals shots sent. What this shows is that the board
counts exactly what it is sent. It says nothing about how `qsim` draws its samples (it does not touch `src/measure.cho`): the board
draws nothing. The strong form of the issue (the board drawing outcomes from a table with a seeded generator, byte-equal to `sample`)
is not done and would first need `qsim`'s generator read and reproduced bit for bit.

Writing this test found a bug in the board design (the first version never cleared bin 0), now fixed and covered by the simulation.

## 2. `tools/fpga/seq.cho`: a circuit's ASAP schedule as pulses, timed by the FPGA

```sh
printf 'time1 20\ntime2 60\nh 0\nh 1\ncx 0 1\nx 0\ncx 1 2\nh 3\n' | ./fpga-seq
```

Reads the circuit text (`time1`, `time2` durations in ns, gates `name q` and `cx a b`, qubits 0 to 5), starts every gate as soon as its qubits
are free (the rule of `sched`; `qsim` does not print its schedule, so it is recomputed here, which is a second implementation of the
rule and is not tested against `qsim`), and plays it on the six LED pins of the board: pin q is high while a gate runs on qubit q. Time is
dilated by 1000 (1 ns of the circuit is 1 microsecond on the pins, 27 ticks of the 27 MHz clock), because the clock's 37 ns tick cannot
resolve 20 ns. An analyzer inside the FPGA records every edge of those pins on the same clock; the tool compares the pin states and the
spacing of the edges with the schedule.

**Measured:** the circuit above, 6 gates: 5 edges recorded, pin states as expected, spacings 540, 1620, 540 and 1080 ticks, exactly the
schedule's (20, 60, 20 and 40 ns x 27). Both the player and the recorder use the same clock, so this shows they agree with each other
and with the schedule, not that the pins are right against an outside instrument (no scope or logic analyser was used). Limits: qubits 0
to 5 only; at most 32 gates; digital pins only, no DAC or ADC; the schedule has no measurement or classical control.

## Not done

Readout classification and mitigation on the board; the fixed-point state-vector engine (an accuracy study; not faster than the CPU, so no
claim); adding the board as another engine of the M3 byte-identity gate (the gate's engines compute amplitudes and this one counts).
