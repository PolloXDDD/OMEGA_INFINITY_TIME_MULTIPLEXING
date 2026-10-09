"""MicroPython board-side server for the custom OMEGA JSON-lines protocol.

Uses the Tiny Tapeout SDK, not undocumented 'w/r/R' firmware commands.
Also importable on CPython for tests with a fake SDK/RTL model.
"""
import json
import sys
import time

PROJECT = "tt_um_omega_infinity_kaoru"
PROFILE = "omega16-constant52-v1"
BASE_BITS = [0, 1, 0, 0, 1, 0, 1, 0]
MAX_FRAME = 4096


def pause_us(microseconds):
    if hasattr(time, "sleep_us"):
        time.sleep_us(microseconds)
    else:
        time.sleep(microseconds / 1000000)


def validate_block(gates, targets):
    if not isinstance(gates, (list, tuple)) or not 1 <= len(gates) <= 16:
        raise ValueError("El bloque debe tener 1..16 gates.")
    if not isinstance(targets, (list, tuple)) or not 1 <= len(targets) <= 16:
        raise ValueError("Se requieren 1..16 targets.")
    for index, gate in enumerate(gates):
        if not isinstance(gate, (list, tuple)) or len(gate) != 3:
            raise ValueError("Un gate debe ser [op,a,b].")
        op, a, b = gate
        if any(type(value) is not int for value in gate):
            raise ValueError("op/a/b deben ser enteros.")
        if not 0 <= op <= 6 or not 0 <= a < 8 + index or not 0 <= b < min(8 + index, 16):
            raise ValueError("Referencia futura o indice fuera del RTL en gate " + str(index))
    for target in targets:
        if type(target) is not int or not 0 <= target < 8 + len(gates):
            raise ValueError("Target fuera de este bloque.")


class BoardController:
    def __init__(self, tt, control_mode, expected_project=PROJECT, settle_us=20):
        self.tt = tt
        self.control_mode = control_mode
        self.expected_project = expected_project
        self.settle_us = settle_us
        self.initialized = False

    def _reset_registers(self):
        tt = self.tt
        tt.clock_project_stop()
        tt.ui_in.value = 0
        tt.uio_in.value = 0
        tt.reset_project(True)
        pause_us(self.settle_us)
        for _ in range(4):
            tt.clock_project_once()
        tt.reset_project(False)
        pause_us(self.settle_us)

    def _read_target(self, target):
        tt = self.tt
        tt.ui_in.value = target << 3
        tt.uio_in.value = 1  # prog_en=1, prog_we=0
        pause_us(self.settle_us)
        tt.clock_project_once()  # Capture target_node, without writing any gate.
        tt.ui_in.value = 0
        tt.uio_in.value = 8  # grid_st is a validity mask in the supplied RTL.
        pause_us(self.settle_us)
        first = int(tt.uo_out.value)
        pause_us(self.settle_us)
        raw = int(tt.uo_out.value)
        if first != raw:
            raise RuntimeError("La salida cambio entre dos lecturas; revisa perfil/pines.")
        if not raw & 4 or (raw & 3) not in (1, 2):
            raise RuntimeError("Los bits DONE/evaluacion no son validos.")
        return raw

    def initialize(self, project):
        if project != self.expected_project:
            raise ValueError("Proyecto distinto al configurado en el servidor: " + self.expected_project)
        self.initialized = False
        tt = self.tt
        tt.clock_project_stop()
        tt.mode = self.control_mode
        try:
            design = getattr(tt.shuttle, project)
        except AttributeError:
            raise RuntimeError("El SDK no tiene el proyecto " + project + "; comprueba los datos de tu shuttle.")
        design.enable()
        # enable() can start a project-specific PWM clock: stop it AFTER selecting.
        tt.clock_project_stop()
        manual = getattr(tt, "manual_project_clock", None)
        if manual is not None and hasattr(manual, "monitoring"):
            manual.monitoring = False
        tt.ui_in.value = 0
        tt.uio_in.value = 0
        # RP2 outputs on uio 0,1,3,4,5,6,7. ASIC uio_oe is 0 in this RTL.
        tt.uio_oe_pico.value = 0xFB
        self._reset_registers()
        raw = [self._read_target(index) for index in range(8)]
        bits = [value & 1 for value in raw]
        if bits != BASE_BITS or any((value >> 3) != 0x12 for value in raw):
            raise RuntimeError("Los nodos base no coinciden con el RTL 0x52; no se cargara una CNF.")
        tt.uio_in.value = 0
        self.initialized = True
        return {"profile": PROFILE, "project": project, "base_bits": bits,
                "max_gates": 16, "a_index_bits": 5, "b_index_bits": 4,
                "clocking": "manual-one-cycle-per-gate"}

    def execute(self, gates, targets):
        if not self.initialized:
            raise RuntimeError("Primero envia init.")
        validate_block(gates, targets)  # Validate everything BEFORE touching registers.
        tt = self.tt
        self._reset_registers()
        for op, a, b in gates:
            tt.ui_in.value = op | (a << 3)
            tt.uio_in.value = 3 | (b << 4)  # prog_en + prog_we
            pause_us(self.settle_us)
            tt.clock_project_once()  # EXACTLY one write; PWM is stopped.
            tt.uio_in.value = 1 | (b << 4)
        raw = [self._read_target(target) for target in targets]
        tt.uio_in.value = 0
        if any((value >> 3) != 0x12 for value in raw):
            raise RuntimeError("Los taps de diagnostico no coinciden con el perfil.")
        return {"values": [value & 1 for value in raw], "raw_outputs": raw,
                "gates_written": len(gates), "outputs_read": len(targets)}

    def shutdown(self):
        self.initialized = False
        self.tt.clock_project_stop()
        self.tt.uio_in.value = 0

    def handle(self, request):
        ident = request.get("id") if isinstance(request, dict) else None
        response = {"v": 1, "id": ident}
        try:
            if not isinstance(request, dict) or request.get("v") != 1:
                raise ValueError("Version de protocolo incorrecta.")
            if type(ident) is not int or ident < 1:
                raise ValueError("id debe ser un entero positivo.")
            command = request.get("cmd")
            if command == "init":
                data = self.initialize(request.get("project"))
            elif command == "block":
                data = self.execute(request.get("gates"), request.get("targets"))
            elif command == "stop":
                self.shutdown()
                data = {"stopped": True}
            else:
                raise ValueError("Comando desconocido.")
            response.update(data)
            response["ok"] = True
        except Exception as exc:
            response["ok"] = False
            response["error"] = str(exc)
            # Leave prog_we low on ALL failures; the next valid block resets state.
            self.tt.clock_project_stop()
            self.tt.uio_in.value = 0
        return response


def read_frame(stream):
    pieces = []
    oversized = False
    while True:
        char = stream.read(1)
        if not char:
            return None
        if char == "\n":
            if oversized:
                raise ValueError("Trama de mas de 4096 caracteres.")
            return "".join(pieces).strip()
        if len(pieces) >= MAX_FRAME:
            oversized = True
        if not oversized:
            pieces.append(char)


def serve(controller, input_stream=None, output_stream=None):
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    while True:
        try:
            frame = read_frame(input_stream)
            if frame is None:
                pause_us(10000)
                continue
            if not frame:
                continue
            request = json.loads(frame)
            answer = controller.handle(request)
        except (ValueError, TypeError) as exc:
            answer = {"v": 1, "id": None, "ok": False, "error": str(exc)}
        output_stream.write(json.dumps(answer) + "\n")
        if hasattr(output_stream, "flush"):
            output_stream.flush()
