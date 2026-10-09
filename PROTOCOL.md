# OMEGA JSON-lines protocol v1

The PC and board implement this custom protocol; it is not a stock Tiny Tapeout
serial command set. USB CDC connects the PC to the board microcontroller, which
uses the official SDK to operate ASIC pins.

Each ASCII request and UTF-8 JSON response ends with a newline. The maximum
frame is 4096 bytes. The PC sends one request and waits for its response before
sending the next. No automatic retry is performed after a timeout or partial
write. Responses echo `v=1`, the request `id`, and an explicit `ok` boolean.

## Initialization

```json
{"v":1,"id":1,"cmd":"init","project":"tt_um_omega_infinity_kaoru"}
```

The board selects the configured project, stops PWM, disables the optional
manual-clock monitor, configures its uio outputs, resets the gate registers,
and reads all eight base nodes. A profile mismatch is an error.

## A block

```json
{"v":1,"id":2,"cmd":"block","gates":[[1,0,1],[0,8,1]],"targets":[8,9]}
```

Each gate is `[opcode, A_source, B_source]`. Gate i has node number 8+i.
There are 1..16 gates per block. A must be 0..7 or an earlier gate node; B
has the same topological restriction AND must be <=15. Opcodes are 0..6.
Targets are 1..16 existing nodes in this block (base nodes also allowed).

Before writing, the controller validates the entire request. It resets the
configuration pointer, puts prog_en/prog_we high, issues EXACTLY ONE clock
cycle per gate, and clears prog_we after each cycle. Target selection occurs
with prog_we=0 and one clock cycle. The controller then sets uio[3] to validate
the combinational output, reads it twice, and returns:

```json
{"v":1,"id":2,"ok":true,"values":[1,1],"raw_outputs":[149,149],"gates_written":2,"outputs_read":2}
```

On completion or error, uio control is returned to 0 and PWM remains stopped.
The PC checks DONE, the complementary evaluation bits and the diagnostic taps.

## Stop

```json
{"v":1,"id":3,"cmd":"stop"}
```

Stops clocking, clears control input and requires a new init before any block.
