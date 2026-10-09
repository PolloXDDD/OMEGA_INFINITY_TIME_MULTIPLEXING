"""Functional RTL model. This is software emulation, not a physical-chip test."""
from omega_core import BASE_BITS, PROFILE, PROJECT, gate_value, validate_block


class RTLModel:
    def __init__(self):
        self.ui = self.uio = 0
        self.rst_n = True
        self.reset()

    def reset(self):
        self.gates = [(0, 0, 0)] * 16
        self.wr_ptr = 0
        self.target = 0

    def rising_clock(self):
        if not self.rst_n:
            self.reset()
        elif self.uio & 1:
            if self.uio & 2:
                self.gates[self.wr_ptr] = (self.ui & 7, (self.ui >> 3) & 31, (self.uio >> 4) & 15)
                self.wr_ptr = (self.wr_ptr + 1) & 15
            else:
                self.target = (self.ui >> 3) & 31

    def nodes(self):
        values = list(BASE_BITS)
        for op, a, b in self.gates:
            # References to current/future gates get 0, exactly as select_node's
            # call sites in the submitted source pass zero for those positions.
            av = values[a] if a < len(values) else 0
            bv = values[b] if b < len(values) else 0
            values.append(gate_value(op, av, bv) if op < 7 else 0)
        return values

    def outputs(self):
        values = self.nodes()
        selected = values[self.target] if self.target < 24 else 0
        stable = int(bool(self.uio & 8))
        taps = sum(BASE_BITS[i] << i for i in range(5))
        return (taps << 3) | (stable << 2) | ((1 - selected) * stable << 1) | selected * stable


class SimBackend:
    name = "sim-functional-rtl"

    def __init__(self, project=PROJECT):
        self.project = project
        self.model = RTLModel()
        self.trace = None

    def initialize(self):
        return {"profile": PROFILE, "project": self.project, "base_bits": list(BASE_BITS),
                "backend": self.name, "max_gates": 16, "b_index_bits": 4}

    def execute(self, gates, targets):
        validate_block(gates, targets)
        model = self.model
        model.reset()
        for op, a, b in gates:
            model.ui, model.uio = op | (a << 3), 3 | (b << 4)
            model.rising_clock()
            model.uio = 1 | (b << 4)
        result = []
        for target in targets:
            model.ui, model.uio = target << 3, 1
            model.rising_clock()
            model.ui, model.uio = 0, 8
            result.append(model.outputs() & 1)
        if self.trace is not None:
            self.trace.append(([list(gate) for gate in gates], list(targets), list(result)))
        return result

    def close(self):
        pass
