"""Versioned JSON-lines USB CDC protocol; timeouts are errors, never zero bits."""
import json
import time

from omega_core import BASE_BITS, PROFILE, PROJECT, validate_block

MAX_FRAME = 4096


class SerialBackend:
    name = "serial-physical-asic"

    def __init__(self, port, *, project=PROJECT, timeout=10.0, baudrate=115200, serial_obj=None):
        if timeout <= 0:
            raise ValueError("El timeout debe ser positivo.")
        self.project = project
        self.timeout = timeout
        self.sequence = 0
        self.buffer = bytearray()
        if serial_obj is None:
            try:
                import serial
            except ImportError as exc:
                raise RuntimeError("Instala pyserial: python -m pip install pyserial") from exc
            self.serial = serial.Serial(port, baudrate, timeout=0.1, write_timeout=timeout)
            time.sleep(0.5)
            self.serial.reset_input_buffer()
        else:
            self.serial = serial_obj

    def _read_line(self, deadline):
        while time.monotonic() < deadline:
            index = self.buffer.find(b"\n")
            if index >= 0:
                line = bytes(self.buffer[:index])
                del self.buffer[:index + 1]
                return line
            chunk = self.serial.read(1)
            if chunk:
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_FRAME:
                    raise RuntimeError("La placa envio una linea de mas de 4096 bytes.")
        raise TimeoutError("La placa no respondio. Comprueba el servidor, el puerto y la seleccion del proyecto.")

    def request(self, command, **fields):
        self.sequence += 1
        message = {"v": 1, "id": self.sequence, "cmd": command, **fields}
        encoded = (json.dumps(message, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        if len(encoded) > MAX_FRAME:
            raise ValueError("La peticion excede el tamano maximo del protocolo.")
        deadline = time.monotonic() + self.timeout
        written = self.serial.write(encoded)
        if written != len(encoded):
            raise RuntimeError("Escritura USB incompleta; no se reenviaron gates automaticamente.")
        while True:
            line = self._read_line(deadline)
            try:
                answer = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                # Boot messages and SDK logging are not protocol responses.
                continue
            if not isinstance(answer, dict) or answer.get("id") != self.sequence:
                continue
            if answer.get("v") != 1 or type(answer.get("ok")) is not bool:
                raise RuntimeError("Respuesta con version o estructura invalida.")
            if not answer["ok"]:
                raise RuntimeError("Placa: " + str(answer.get("error", "error sin descripcion")))
            return answer

    def initialize(self):
        answer = self.request("init", project=self.project)
        if answer.get("profile") != PROFILE or answer.get("project") != self.project:
            raise RuntimeError("El servidor/proyecto no coincide con el perfil de OMEGA esperado.")
        if answer.get("base_bits") != list(BASE_BITS):
            raise RuntimeError("Los ocho nodos base no coinciden con el RTL del ZIP (0x52).")
        return {**answer, "backend": self.name}

    def execute(self, gates, targets):
        validate_block(gates, targets)
        answer = self.request("block", gates=gates, targets=targets)
        raw = answer.get("raw_outputs")
        values = answer.get("values")
        if not isinstance(raw, list) or not isinstance(values, list) or len(raw) != len(targets) or len(values) != len(targets):
            raise RuntimeError("La placa devolvio una cantidad incorrecta de resultados.")
        for raw_byte, value in zip(raw, values):
            if type(raw_byte) is not int or not 0 <= raw_byte <= 255 or type(value) is not int or value not in (0, 1):
                raise RuntimeError("Respuesta USB con valores fuera de rango.")
            if not raw_byte & 4 or (raw_byte & 3) not in (1, 2) or (raw_byte & 1) != value:
                raise RuntimeError("DONE o los bits de evaluacion no son validos.")
            if (raw_byte >> 3) != 0x12:
                raise RuntimeError("Los taps de diagnostico cambiaron; se detuvo la ejecucion.")
        return values

    def close(self):
        self.serial.close()
